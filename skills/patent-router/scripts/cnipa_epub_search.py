#!/usr/bin/env python3
"""CNIPA ePub Chinese-patent discovery adapter.

This adapter only performs first-round discovery against the official CNIPA
publication search page.  Its output is deliberately marked as discovery
evidence: title, result-page abstract and publication metadata are not enough
to decide novelty, inventive step, FTO or legal status.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


EPUB_BASE = "http://epub.cnipa.gov.cn/"
SCHEMA_VERSION = "cnipa-epub-discovery/v1"
TYPE_CHECKBOXES = {
    "all": {"fmgb": True, "fmsq": True, "xxsq": True, "wgsq": True},
    "invention": {"fmgb": True, "fmsq": True, "xxsq": False, "wgsq": False},
    "utility_model": {"fmgb": False, "fmsq": False, "xxsq": True, "wgsq": False},
    "design": {"fmgb": False, "fmsq": False, "xxsq": False, "wgsq": True},
}
CNIPA_COMPAT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
RESULT_READY_JS = """(titles) => {
    const title = document.title.trim();
    if (title === titles.noHit) return true;
    if (title !== titles.result) return false;
    const result = document.querySelector("#result");
    if (!result) return false;
    if (result.querySelector("div.item, h1.title")) return true;
    const body = result.innerText || "";
    return ["无查询结果", "没有找到", "未检索到", "0条"].some(x => body.includes(x));
}"""


class QueryRejected(ValueError):
    """The query is too sensitive or too broad to send to the HTTP endpoint."""


class InteractionRequired(RuntimeError):
    """The official page needs manual interaction or its DOM has changed."""


def clean_text(value: Any) -> str:
    text = html_module.unescape(str(value or ""))
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def validate_terms(terms: list[str]) -> list[str]:
    if not 1 <= len(terms) <= 8:
        raise QueryRejected("每次须提供 1 至 8 个脱敏短检索词")
    normalized: list[str] = []
    seen: set[str] = set()
    sensitive_patterns = (
        re.compile(r"https?://", re.I),
        re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
        re.compile(r"(?<!\d)\d{11,18}(?!\d)"),
        re.compile(r"(?:身份证|统一社会信用代码|手机号|联系电话)\s*[：:]?"),
    )
    for raw in terms:
        term = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not term:
            raise QueryRejected("检索词不能为空")
        if "\n" in str(raw) or "\r" in str(raw):
            raise QueryRejected("不得发送多行技术交底或权利要求原文")
        if len(term) > 32:
            raise QueryRejected("单个检索词超过 32 个字符，请拆成脱敏技术词或短语")
        if any(pattern.search(term) for pattern in sensitive_patterns):
            raise QueryRejected("检索词疑似包含网址、联系方式或身份标识，请先脱敏")
        key = term.casefold()
        if key not in seen:
            normalized.append(term)
            seen.add(key)
    return normalized


def checkbox_states(patent_type: str) -> dict[str, bool]:
    try:
        return dict(TYPE_CHECKBOXES[patent_type])
    except KeyError as exc:
        raise ValueError(f"不支持的专利类型: {patent_type}") from exc


def extract_field(item_html: str, labels: tuple[str, ...]) -> str | None:
    label_expression = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"<dt[^>]*>\s*(?:{label_expression})\s*[：:]?\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        item_html,
        flags=re.I | re.S,
    )
    value = clean_text(match.group(1)) if match else ""
    return re.sub(r"\s*全部\s*$", "", value).strip() or None


def normalize_publication_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s+", "", value).upper()
    return normalized if re.match(r"^(?:CN|ZL)", normalized) else None


def normalize_application_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s+", "", value).upper()
    return normalized if re.match(r"^(?:CN)?\d{8,}(?:\.\d+)?$", normalized) else None


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.findall(r"\d+", value)
    if len(digits) < 3:
        return None
    year, month, day = map(int, digits[:3])
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def split_item_blocks(page_html: str) -> list[str]:
    starts = list(
        re.finditer(
            r'<div\s+[^>]*class=["\'][^"\']*\bitem\b[^"\']*["\'][^>]*>',
            page_html,
            flags=re.I,
        )
    )
    return [
        page_html[match.start() : starts[index + 1].start() if index + 1 < len(starts) else len(page_html)]
        for index, match in enumerate(starts)
    ]


def parse_result_html(
    page_html: str,
    *,
    matched_term: str,
    retrieved_at: str,
    source_verified: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item_html in split_item_blocks(page_html):
        title_match = re.search(
            r'<h1\s+[^>]*class=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</h1>',
            item_html,
            flags=re.I | re.S,
        )
        title = clean_text(title_match.group(1)) if title_match else None
        publication_number = normalize_publication_number(
            extract_field(item_html, ("申请公布号", "授权公告号"))
        )
        link_match = re.search(
            r'(?:title|href)=["\'](https?://epub\.cnipa\.gov\.cn/patent/[^"\']+)["\']',
            item_html,
            flags=re.I,
        )
        source_url = link_match.group(1).strip() if link_match else None
        if not publication_number and source_url:
            number_match = re.search(r"/patent/((?:CN|ZL)[^/?#]+)", source_url, flags=re.I)
            publication_number = normalize_publication_number(
                number_match.group(1) if number_match else None
            )
        if not source_url and publication_number:
            source_url = urljoin(EPUB_BASE, f"patent/{publication_number}")
        abstract = extract_field(item_html, ("摘要",))
        publication_date = normalize_date(
            extract_field(item_html, ("申请公布日", "授权公告日"))
        )
        application_number = normalize_application_number(
            extract_field(item_html, ("申请号",))
        )
        if not any((title, publication_number, source_url)):
            continue
        abstract_complete = bool(abstract) and not bool(re.search(r"(?:\.\.\.|…)$", abstract))
        records.append(
            {
                "publication_number": publication_number,
                "application_number": application_number,
                "title": title,
                "abstract": abstract,
                "abstract_scope": (
                    "result-page-abstract" if abstract_complete else "result-page-snippet"
                ),
                "abstract_complete": abstract_complete,
                "publication_date": publication_date,
                "priority_date": None,
                "claims": None,
                "description": None,
                "legal_status": "无法确认",
                "status_sources": [],
                "source_url": source_url,
                "provider": "CNIPA_EPUB",
                "official_source": True,
                "source_verified": source_verified,
                "retrieved_at": retrieved_at,
                "evidence_stage": "discovery",
                "prior_art_eligible": False,
                "matched_terms": [matched_term],
            }
        )
    return records


def deduplicate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        key = (
            record.get("publication_number")
            or record.get("source_url")
            or clean_text(record.get("title")).casefold()
        )
        if not key:
            continue
        if key in index:
            merged = index[key]
            merged["matched_terms"] = list(
                dict.fromkeys((merged.get("matched_terms") or []) + (record.get("matched_terms") or []))
            )
            continue
        index[key] = record
        output.append(record)
    return output


def apply_type_filter(page: Any, patent_type: str) -> None:
    for checkbox_id, wanted in checkbox_states(patent_type).items():
        locator = page.locator(f"#{checkbox_id}")
        if locator.count() == 0:
            continue
        if wanted:
            locator.check(force=True)
        else:
            locator.uncheck(force=True)


def browser_runtime_policy(
    *, browser_channel: str, headed: bool, browser_mode: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    launch_options: dict[str, Any] = {"headless": not headed}
    if browser_channel == "chrome":
        launch_options["channel"] = "chrome"
    context_options: dict[str, Any] = {
        "locale": "zh-CN",
        "viewport": {"width": 1280, "height": 900},
    }
    if browser_mode == "cnipa-compatible":
        launch_options["args"] = ["--disable-blink-features=AutomationControlled"]
        context_options["user_agent"] = CNIPA_COMPAT_USER_AGENT
    elif browser_mode != "strict":
        raise ValueError(f"不支持的浏览器模式: {browser_mode}")
    audit = {
        "mode": browser_mode,
        "channel": browser_channel,
        "headed": headed,
        "automation_controlled_flag_disabled": browser_mode == "cnipa-compatible",
        "desktop_user_agent": browser_mode == "cnipa-compatible",
        "sandbox_disabled": False,
        "captcha_bypass": False,
        "persistent_user_profile": False,
    }
    return launch_options, context_options, audit


def wait_home(page: Any, timeout_ms: int) -> None:
    page.goto(EPUB_BASE, wait_until="load", timeout=max(timeout_ms, 120_000))
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(3_000)
        if page.query_selector("#searchStr"):
            return
    body = ""
    try:
        body = clean_text(page.content())
    except Exception:
        pass
    hint = "页面可能需要人工验证" if any(word in body for word in ("验证", "验证码", "滑块")) else "页面结构可能已变化"
    raise InteractionRequired(f"国知局检索框在限时内不可用，{hint}；本适配器不会绕过验证")


def fetch_result_html(page: Any, term: str, patent_type: str, timeout_ms: int) -> str:
    wait_home(page, timeout_ms)
    apply_type_filter(page, patent_type)
    page.locator("#searchStr").fill(term)
    form = page.locator("#indexForm")
    if form.count() == 0:
        raise InteractionRequired("未找到国知局首页检索表单，页面结构可能已变化")
    try:
        with page.expect_navigation(wait_until="commit", timeout=timeout_ms):
            form.evaluate("form => form.submit()")
        page.wait_for_function(
            RESULT_READY_JS,
            arg={"result": "专利查询结果展示", "noHit": "无查询结果"},
            timeout=timeout_ms,
        )
    except Exception as exc:
        raise InteractionRequired("国知局结果页未在限时内就绪；可能需要人工验证或官方页面已改版") from exc
    for attempt in range(4):
        try:
            return page.content()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("无法读取国知局结果页")


def fetch_with_retries(
    context: Any,
    term: str,
    patent_type: str,
    timeout_ms: int,
    *,
    retry_count: int,
    retry_delay_seconds: float,
) -> tuple[str, int, list[dict[str, Any]]]:
    """Fetch one term with bounded retries and a fresh page per attempt."""
    failures: list[dict[str, Any]] = []
    for attempt in range(retry_count + 1):
        page = context.new_page()
        try:
            return (
                fetch_result_html(page, term, patent_type, timeout_ms),
                attempt + 1,
                failures,
            )
        except InteractionRequired as exc:
            failures.append(
                {"term": term, "attempt": attempt + 1, "message": str(exc)}
            )
            if attempt >= retry_count:
                raise InteractionRequired(
                    f"国知局检索连续 {attempt + 1} 次未就绪；最后错误：{exc}"
                ) from exc
            time.sleep(retry_delay_seconds * (attempt + 1))
        finally:
            page.close()
    raise InteractionRequired("国知局检索未生成结果页")


def live_search(
    terms: list[str],
    *,
    patent_type: str,
    timeout_seconds: float,
    retry_count: int,
    retry_delay_seconds: float,
    headed: bool,
    browser_channel: str,
    browser_mode: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 Playwright；请安装 requirements-cnipa.txt 并执行 playwright install chromium"
        ) from exc
    retrieved_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    timeout_ms = max(5_000, int(timeout_seconds * 1000))
    with sync_playwright() as playwright:
        launch_options, context_options, runtime_audit = browser_runtime_policy(
            browser_channel=browser_channel,
            headed=headed,
            browser_mode=browser_mode,
        )
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(**context_options)
        attempts_total = 0
        retry_failures: list[dict[str, Any]] = []
        try:
            for term in terms:
                page_html, attempts, failures = fetch_with_retries(
                    context,
                    term,
                    patent_type,
                    timeout_ms,
                    retry_count=retry_count,
                    retry_delay_seconds=retry_delay_seconds,
                )
                attempts_total += attempts
                retry_failures.extend(failures)
                records.extend(
                    parse_result_html(
                        page_html,
                        matched_term=term,
                        retrieved_at=retrieved_at,
                        source_verified=True,
                    )
                )
        finally:
            context.close()
            browser.close()
    runtime_audit["attempts_total"] = attempts_total
    runtime_audit["retry_failures"] = retry_failures
    return deduplicate_records(records), retrieved_at, runtime_audit


def build_payload(
    *,
    terms: list[str],
    patent_type: str,
    retrieved_at: str,
    records: list[dict[str, Any]],
    source_mode: str,
    browser_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "CNIPA_EPUB",
        "provider_url": EPUB_BASE,
        "transport_security": "http",
        "source_mode": source_mode,
        "browser_policy": browser_policy,
        "query": {"terms": terms, "patent_type": patent_type},
        "retrieved_at": retrieved_at,
        "result_count": len(records),
        "records": records,
        "decision_boundary": (
            "本结果仅用于中国专利首轮发现。公开日、优先权、全文、权利要求、附图和法律状态"
            "未经逐项复核前，prior_art_eligible 固定为 false，不得据此作查新、FTO 或法律结论。"
        ),
        "privacy_warning": (
            "国知局公布公告入口当前为 HTTP；只发送脱敏短技术词，不发送未公开交底、权利要求原文、"
            "企业秘密、个人信息或身份标识。"
        ),
    }


def emit_error(error_code: str, message: str) -> None:
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "error",
                "error_code": error_code,
                "message": message,
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="国知局公布公告中国专利首轮发现适配器")
    parser.add_argument("terms", nargs="*", help="1 至 8 个脱敏短检索词；每项不超过 32 字符")
    parser.add_argument(
        "--type",
        choices=tuple(TYPE_CHECKBOXES),
        default="all",
        dest="patent_type",
    )
    parser.add_argument("--input-html", type=Path, help="只解析已保存的结果页 HTML，不联网")
    parser.add_argument("--output", type=Path, help="将结构化 JSON 同时写入指定路径")
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    parser.add_argument("--headed", action="store_true", help="显示浏览器，供用户自行完成官方页面交互")
    parser.add_argument(
        "--browser-channel",
        choices=("chromium", "chrome"),
        default="chromium",
        help="使用 Playwright Chromium 或本机正式 Chrome",
    )
    parser.add_argument(
        "--browser-mode",
        choices=("cnipa-compatible", "strict"),
        default="cnipa-compatible",
        help=(
            "默认使用国知局兼容模式，公开设置桌面 UA 并关闭 AutomationControlled 标记；"
            "strict 不修改这两项。两种模式都保留浏览器沙箱且不处理验证码"
        ),
    )
    arguments = parser.parse_args()
    try:
        terms = validate_terms(arguments.terms or (["离线样例"] if arguments.input_html else []))
        if arguments.max_results < 1:
            raise ValueError("--max-results 必须大于 0")
        if arguments.retry_count < 0:
            raise ValueError("--retry-count 不得小于 0")
        if arguments.retry_delay_seconds < 0:
            raise ValueError("--retry-delay-seconds 不得小于 0")
        if arguments.input_html:
            retrieved_at = datetime.now(timezone.utc).isoformat()
            page_html = arguments.input_html.read_text(encoding="utf-8")
            records = parse_result_html(
                page_html,
                matched_term=terms[0],
                retrieved_at=retrieved_at,
                source_verified=False,
            )
            source_mode = "offline-html"
            browser_policy = None
        else:
            records, retrieved_at, browser_policy = live_search(
                terms,
                patent_type=arguments.patent_type,
                timeout_seconds=arguments.timeout_seconds,
                retry_count=arguments.retry_count,
                retry_delay_seconds=arguments.retry_delay_seconds,
                headed=arguments.headed,
                browser_channel=arguments.browser_channel,
                browser_mode=arguments.browser_mode,
            )
            source_mode = "live-browser"
        records = deduplicate_records(records)[: arguments.max_results]
        payload = build_payload(
            terms=terms,
            patent_type=arguments.patent_type,
            retrieved_at=retrieved_at,
            records=records,
            source_mode=source_mode,
            browser_policy=browser_policy,
        )
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        print(rendered)
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(rendered + "\n", encoding="utf-8")
        return 0
    except QueryRejected as exc:
        emit_error("QUERY_REJECTED", str(exc))
        return 2
    except InteractionRequired as exc:
        emit_error("INTERACTION_REQUIRED", str(exc))
        return 3
    except (OSError, RuntimeError, ValueError) as exc:
        emit_error("PROVIDER_UNAVAILABLE", str(exc))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
