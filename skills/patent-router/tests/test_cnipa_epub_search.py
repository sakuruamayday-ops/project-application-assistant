import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cnipa_epub_search.py"
SPEC = importlib.util.spec_from_file_location("cnipa_epub_search", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


SAMPLE_HTML = """
<html><head><title>专利查询结果展示</title></head><body>
<div id="result" class="overview-default">
  <div class="item">
    <h1 class="title">一种知识图谱构建方法</h1>
    <div class="qrcode" title="http://epub.cnipa.gov.cn/patent/CN123456789A"></div>
    <dl>
      <dt>申请公布号：</dt><dd>CN 123456789 A</dd>
      <dt>申请公布日：</dt><dd>2024年06月18日</dd>
      <dt>摘要：</dt><dd>本发明公开一种面向图数据的构建方法。</dd>
    </dl>
  </div>
  <div class="item featured">
    <h1 class="title">一种图数据库检索装置</h1>
    <a href="http://epub.cnipa.gov.cn/patent/CN987654321U">详情</a>
    <dl>
      <dt>授权公告号:</dt><dd>CN987654321U</dd>
      <dt>授权公告日:</dt><dd>2023-02-03</dd>
      <dt>摘要:</dt><dd>本实用新型涉及图数据库检索...</dd>
    </dl>
  </div>
</div></body></html>
"""


class ParseTests(unittest.TestCase):
    def test_parses_official_cards_and_dates(self):
        rows = MODULE.parse_result_html(
            SAMPLE_HTML,
            matched_term="知识图谱",
            retrieved_at="2026-08-14T00:00:00+00:00",
            source_verified=True,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["publication_number"], "CN123456789A")
        self.assertEqual(rows[0]["publication_date"], "2024-06-18")
        self.assertEqual(rows[0]["abstract_scope"], "result-page-abstract")
        self.assertFalse(rows[0]["prior_art_eligible"])
        self.assertEqual(rows[0]["legal_status"], "无法确认")

    def test_marks_truncated_abstract(self):
        rows = MODULE.parse_result_html(
            SAMPLE_HTML,
            matched_term="图数据库",
            retrieved_at="2026-08-14T00:00:00+00:00",
            source_verified=False,
        )
        self.assertFalse(rows[1]["abstract_complete"])
        self.assertEqual(rows[1]["abstract_scope"], "result-page-snippet")

    def test_deduplicates_and_merges_terms(self):
        first = MODULE.parse_result_html(
            SAMPLE_HTML,
            matched_term="知识图谱",
            retrieved_at="2026-08-14T00:00:00+00:00",
            source_verified=True,
        )
        second = MODULE.parse_result_html(
            SAMPLE_HTML,
            matched_term="图数据库",
            retrieved_at="2026-08-14T00:00:00+00:00",
            source_verified=True,
        )
        rows = MODULE.deduplicate_records(first + second)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["matched_terms"], ["知识图谱", "图数据库"])


class BoundaryTests(unittest.TestCase):
    def test_checkbox_presets(self):
        invention = MODULE.checkbox_states("invention")
        self.assertTrue(invention["fmgb"] and invention["fmsq"])
        self.assertFalse(invention["xxsq"] or invention["wgsq"])
        design = MODULE.checkbox_states("design")
        self.assertTrue(design["wgsq"])
        self.assertFalse(design["fmgb"])

    def test_rejects_confidential_long_sentence(self):
        with self.assertRaises(MODULE.QueryRejected):
            MODULE.validate_terms(["一种包含客户未公开配方参数及完整工艺窗口的超长技术交底内容不得直接发送到外部网站"])

    def test_rejects_identity_identifier(self):
        with self.assertRaises(MODULE.QueryRejected):
            MODULE.validate_terms(["统一社会信用代码 91330100123456789X"])

    def test_payload_keeps_discovery_boundary(self):
        payload = MODULE.build_payload(
            terms=["知识图谱"],
            patent_type="invention",
            retrieved_at="2026-08-14T00:00:00+00:00",
            records=[],
            source_mode="offline-html",
        )
        self.assertEqual(payload["schema_version"], "cnipa-epub-discovery/v1")
        self.assertIn("prior_art_eligible", payload["decision_boundary"])
        self.assertEqual(payload["transport_security"], "http")

    def test_cnipa_compatibility_keeps_sandbox(self):
        launch, context, audit = MODULE.browser_runtime_policy(
            browser_channel="chromium",
            headed=False,
            browser_mode="cnipa-compatible",
        )
        self.assertIn("--disable-blink-features=AutomationControlled", launch["args"])
        self.assertNotIn("--no-sandbox", launch["args"])
        self.assertIn("user_agent", context)
        self.assertFalse(audit["sandbox_disabled"])
        self.assertFalse(audit["captcha_bypass"])

    def test_strict_browser_mode_changes_no_fingerprint_fields(self):
        launch, context, audit = MODULE.browser_runtime_policy(
            browser_channel="chrome",
            headed=True,
            browser_mode="strict",
        )
        self.assertNotIn("args", launch)
        self.assertNotIn("user_agent", context)
        self.assertEqual(launch["channel"], "chrome")
        self.assertFalse(audit["automation_controlled_flag_disabled"])

    def test_zero_result_is_valid_discovery_not_provider_failure(self):
        rows = MODULE.parse_result_html(
            '<html><head><title>无查询结果</title></head><body><div id="result">无查询结果</div></body></html>',
            matched_term="不存在的公开测试词",
            retrieved_at="2026-08-14T00:00:00+00:00",
            source_verified=True,
        )
        payload = MODULE.build_payload(
            terms=["不存在的公开测试词"],
            patent_type="all",
            retrieved_at="2026-08-14T00:00:00+00:00",
            records=rows,
            source_mode="offline-html",
        )
        self.assertEqual(payload["result_count"], 0)
        self.assertNotEqual(payload.get("status"), "error")

    def test_interaction_failure_retries_with_fresh_page_and_records_attempts(self):
        class Page:
            def close(self):
                return None

        class Context:
            def __init__(self):
                self.pages = 0

            def new_page(self):
                self.pages += 1
                return Page()

        context = Context()
        calls = [MODULE.InteractionRequired("暂时未就绪"), SAMPLE_HTML]

        def fake_fetch(*_args, **_kwargs):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(MODULE, "fetch_result_html", side_effect=fake_fetch), patch.object(
            MODULE.time, "sleep"
        ):
            page_html, attempts, failures = MODULE.fetch_with_retries(
                context,
                "知识图谱",
                "invention",
                5_000,
                retry_count=1,
                retry_delay_seconds=0,
            )
        self.assertIn("CN123456789A", page_html)
        self.assertEqual(attempts, 2)
        self.assertEqual(context.pages, 2)
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
