from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.build_knowledge_content_index import extract
except ModuleNotFoundError:
    from build_knowledge_content_index import extract


ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
    ".wps", ".md", ".txt", ".csv",
}
HARD_EXCLUDED_TERMS = (
    "身份证", "护照", "手机号", "通讯录", "银行流水", "银行卡", "银行回单",
    "工资", "社保", "养老保险", "劳动合同", "审计", "纳税申报", "发票",
    "合同", "客户名单", "人员名单", "人员清单", "员工名单",
    "研发人员清单", "营业执照", "学历证书", "毕业证", "职称证书", "专利证书",
    "证书", "签章", "盖章", "财务报表", "银行对账单",
    "检测报告", "验收报告", "查新报告", "鉴定证书", "受理通知书", "授权通知书",
    "证明材料", "佐证材料", "装订材料", "整套材料", "提成表", "每月绩效",
    "项目投资清单", "财务尽调", "尽调报告", "研发账面凭证",
)
LOW_VALUE_TERMS = (
    "副本", "复件", "备份", "缓存", "desktop-attachments", "node_modules",
    "聊天记录", "微信图片", "截图", "照片", "扫描件", "垃圾堆", "回收站",
)
CASE_SPECIFIC_PATH_TERMS = (
    "普通授权发明", "三个月授权发明", "一年授权发明", "各类体系认证",
    "2025年 吴丹副高", "专业工作项目", "年度总结", "/文献/", "企业资料",
    "首版次案例", "初稿-客户", "华味亨", "康纳-尖兵", "东光", "案列",
    "评价内容-", "可跟进客户", "客户信息", "客户签约", "售后相关", "规划书",
    "提升方案", "工作分配", "研发支出辅助账", "/明细账/", "立项验收",
    "认证申请包", "现场评审材料", "制度-2019", "加红头文件",
    "附件-高新申报整理", "表彰培训模板",
)
METHOD_SIGNALS = (
    "模板", "空白", "样表", "指引", "指南", "培训", "课件", "总结", "流程",
    "注意事项", "操作", "攻略", "评分", "评价", "管理办法", "细则", "清单",
    "撰写", "填报说明", "常见问题", "政策解读", "标准服务", "质量", "审核",
    "评审要点", "答辩技巧", "计算逻辑", "方法", "规范", "制度", "条件",
)
POLICY_SIGNALS = (
    "通知", "办法", "指南", "指引", "细则", "条件", "要求", "目录", "规范",
    "政策", "评价", "管理", "实施方案", "征集", "认定", "验收", "申报",
)
IP_METHOD_SIGNALS = (
    "检索", "布局", "交底", "撰写", "申请流程", "侵权", "预警", "分析", "分类号",
    "专利法", "审查指南", "费用", "模板", "清单", "指南", "培训", "流程", "办法",
)
HIGH_RISK_PATTERNS = {
    "id_card": re.compile(
        r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
        r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)"
    ),
    "credential": re.compile(
        r"(?i)(?:access[_ -]?token|api[_ -]?key|password|cookie|secret)\s*[:=]"
    ),
    "bank_account_context": re.compile(
        r"(?:银行账号|银行卡号|收款账号|账户号码|卡号)\s*[:：]?\s*\d{12,30}"
    ),
    "personal_contact": re.compile(
        r"(?<!\d)1[3-9]\d{9}(?!\d)|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    ),
}
SHICHEN_ROOTS = (
    "申报信息指引/01-浙江省高新申报指引及实务",
    "申报信息指引/02-浙江省加计扣除指引及实务",
    "申报信息指引/专精特新",
    "申报信息指引/专精特新小巨人",
    "申报信息指引/科创空间/00-科创空间售前材料包",
    "申报信息指引/众创空间",
    "申报信息指引/临安区制造业企业智能化诊断项目",
    "申报信息指引/杭州市专利试点示范培训",
    "申报信息指引/浙江省双软认定",
    "申报信息指引/浙江省经济和信息化厅 浙江省财政厅关于组织实施生产制造方式转型示范项目计划的通知",
    "培训/2022高新",
    "培训/双软认定",
    "资料清单",
    "高新制度",
    "共创/培训",
    "共创/材料清单",
    "共创/2026年新版专精特新中小企业及专家特新“小巨人”评分表参考",
    "2019/模板",
)
SPECIAL_FILES = {
    "2025年软件相关政策项目汇总.xlsx": ("40_内部培训与方法", "软件与数字经济"),
    "研发费用加计扣除-工程设计公司专场.pptx": ("40_内部培训与方法", "加计扣除"),
    "消费品标准欺诈案例盘点.pptx": ("40_内部培训与方法", "标准与质量"),
    "01-国家高新技术企业认定知识库.md": ("40_内部培训与方法", "项目知识库"),
    "02-专精特新及小巨人认定知识库.md": ("40_内部培训与方法", "项目知识库"),
    "03-首台套首版次数字化未来工厂知识库.md": ("40_内部培训与方法", "项目知识库"),
    "04-管理制度模板知识库.md": ("40_内部培训与方法", "项目知识库"),
    "查新委托书.doc": ("30_空白模板", "知识产权"),
    "攻关需求评测分析报告_2023-02-24.pdf": ("40_内部培训与方法", "科技计划"),
    "杭州市研发中心.pptx": ("40_内部培训与方法", "企业研发机构"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第二轮筛选并导入高价值知识资料")
    parser.add_argument("--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--shichen-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_SOURCE_ROOT", Path.cwd() / "source-materials")))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-knowledge", action="store_true")
    parser.add_argument("--skip-shichen", action="store_true")
    parser.add_argument("--shichen-path", action="append", default=[])
    parser.add_argument("--report-tag", default="all")
    parser.add_argument("--max-depth", type=int)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def existing_package_hashes(
    package_root: Path, manifest_path: Path, report_root: Path
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            digest = str(item.get("sha256", ""))
            source = Path(str(item.get("source_path", "")))
            if digest and source.exists():
                hashes.setdefault(digest, str(source))
    for report_path in report_root.glob("*_executed.csv"):
        if report_path.name.startswith("._"):
            continue
        try:
            with report_path.open(encoding="utf-8-sig") as source:
                for row in csv.DictReader(source):
                    digest = str(row.get("sha256", ""))
                    destination = str(
                        row.get("destination", "") or row.get("destination_or_existing", "")
                    )
                    if digest and destination and Path(destination).exists():
                        hashes.setdefault(digest, destination)
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    if hashes:
        return hashes
    for path in package_root.rglob("*"):
        if path.is_file() and not path.name.startswith("._"):
            hashes.setdefault(sha256_file(path), str(path))
    return hashes


def load_content(database_path: Path) -> dict[str, str]:
    if not database_path.exists():
        return {}
    with sqlite3.connect(database_path) as connection:
        return {
            str(digest): str(content)
            for digest, content in connection.execute("SELECT sha256, content FROM documents")
        }


def basic_rejection(path: Path) -> str | None:
    text = str(path).lower()
    if path.name.startswith(("._", "~$")) or path.name == ".DS_Store":
        return "system_or_temporary"
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return "unsupported_format"
    if any(term.lower() in text for term in HARD_EXCLUDED_TERMS):
        return "excluded_sensitive_evidence"
    if any(term.lower() in text for term in LOW_VALUE_TERMS):
        return "low_value_or_duplicate_name"
    return None


def classify_value(path: Path, role: str = "", top_category: str = "") -> tuple[str, str] | None:
    filename = path.name.lower()
    path_text = str(path).lower()
    category = top_category or "跨项目通用"
    if path.name in SPECIAL_FILES:
        return SPECIAL_FILES[path.name]
    if role in {"10_政策与通知", "20_项目规则与指南", "50_名单与对标"}:
        if not any(term.lower() in filename for term in POLICY_SIGNALS):
            return None
        layer = {
            "10_政策与通知": "10_政策与目录",
            "20_项目规则与指南": "20_申报指南与规则",
            "50_名单与对标": "50_名单与对标",
        }[role]
        return layer, category
    if "申报信息指引" in path_text and any(term.lower() in filename for term in POLICY_SIGNALS):
        if any(term in filename for term in ("通知", "办法", "细则", "政策", "目录")):
            return "10_政策与目录", category
        return "20_申报指南与规则", category
    if "专利" in path_text or role == "70_知识产权":
        if any(term.lower() in filename for term in IP_METHOD_SIGNALS):
            return "70_知识产权方法", category
        return None
    if any(term.lower() in filename for term in METHOD_SIGNALS):
        if any(term in filename for term in ("模板", "空白", "样表")):
            return "30_空白模板", category
        return "40_内部培训与方法", category
    return None


def case_specific_rejection(path: Path, layer: str) -> str | None:
    normalized = str(path).replace("\\", "/").lower()
    if any(term.lower() in normalized for term in CASE_SPECIFIC_PATH_TERMS):
        return "case_specific_source"
    if "有限公司" in normalized or "股份有限公司" in normalized:
        return "company_specific_source"
    if layer in {"30_空白模板", "40_内部培训与方法", "60_脱敏案例", "70_知识产权方法"}:
        if re.search(r"(?:^|[-_ ])cn\d{8,}[a-z]?", path.name.lower()):
            return "individual_patent_document"
        if "发明专利-" in path.name or "发明证书" in path.name:
            return "individual_patent_document"
    return None


def unique_destination(destination: Path, digest: str) -> Path:
    if not destination.exists():
        return destination
    if sha256_file(destination) == digest:
        return destination
    return destination.with_name(f"{destination.stem}__{digest[:8]}{destination.suffix}")


def main() -> None:
    args = parse_args()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    shichen_root = args.shichen_root.expanduser().resolve()
    package_root = knowledge_root / "_云端知识库"
    index_root = knowledge_root / "_云端迁移索引"
    package_hashes = existing_package_hashes(
        package_root, index_root / "cloud_package_index" / "manifest.jsonl", index_root
    )
    content = load_content(index_root / "knowledge_content.sqlite3")
    records: list[dict[str, object]] = []
    candidates: list[tuple[Path, str, str, str, str]] = []

    if not args.skip_knowledge:
        manifest = [
            json.loads(line)
            for line in (index_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for item in manifest:
            relative = str(item["relative_path"])
            if relative.startswith(("_云端知识库/", "_云端迁移索引/")):
                continue
            source = Path(str(item["source_path"]))
            reason = basic_rejection(source)
            if reason:
                continue
            classified = classify_value(source, str(item["document_role"]), str(item["top_category"]))
            if classified:
                layer, category = classified
                if not case_specific_rejection(source, layer):
                    candidates.append((source, layer, category, str(item.get("sha256", "")), "knowledge_disk"))

    configured_roots = tuple(args.shichen_path) if args.shichen_path else SHICHEN_ROOTS
    for configured_root in () if args.skip_shichen else configured_roots:
        print(f"scanning_shichen={configured_root}", flush=True)
        source_root = shichen_root / configured_root
        if not source_root.exists():
            continue
        scanned_files = 0
        sources = (source_root,) if source_root.is_file() else source_root.rglob("*")
        for source in sources:
            if not source.is_file():
                continue
            if args.max_depth is not None and len(source.relative_to(source_root).parts) > args.max_depth:
                continue
            scanned_files += 1
            if scanned_files % 250 == 0:
                print(f"scanned_files={scanned_files} root={configured_root}", flush=True)
            reason = basic_rejection(source)
            if reason:
                continue
            classified = classify_value(source, top_category=Path(configured_root).name)
            if classified:
                layer, category = classified
                if not case_specific_rejection(source, layer):
                    candidates.append((source, layer, category, "", "shichen_disk"))

    seen_sources: set[str] = set()
    for position, (source, layer, category, known_digest, origin) in enumerate(candidates, start=1):
        if str(source) in seen_sources:
            continue
        seen_sources.add(str(source))
        digest = known_digest or sha256_file(source)
        if digest in package_hashes:
            records.append({
                "source": str(source), "origin": origin, "layer": layer, "category": category,
                "action": "package_duplicate", "reason": "same_sha256", "sha256": digest,
                "size_bytes": source.stat().st_size, "destination": package_hashes[digest],
            })
            continue
        extracted = content.get(digest, "")
        if origin == "shichen_disk" and not extracted:
            try:
                extracted, extraction_status = extract(source, source.suffix.lower())
            except Exception as error:
                extracted, extraction_status = "", f"error:{type(error).__name__}"
            if (
                extraction_status != "indexed"
                and layer not in {"10_政策与目录", "20_申报指南与规则", "50_名单与对标"}
            ):
                records.append({
                    "source": str(source), "origin": origin, "layer": layer, "category": category,
                    "action": "skipped", "reason": "no_fulltext_for_dlp:" + extraction_status,
                    "sha256": digest, "size_bytes": source.stat().st_size,
                })
                continue
        if origin == "knowledge_disk" and not extracted:
            records.append({
                "source": str(source), "origin": origin, "layer": layer, "category": category,
                "action": "skipped", "reason": "no_fulltext_for_dlp", "sha256": digest,
                "size_bytes": source.stat().st_size,
            })
            continue
        if extracted:
            hits = [name for name, pattern in HIGH_RISK_PATTERNS.items() if pattern.search(extracted)]
            if hits and layer not in {"10_政策与目录", "20_申报指南与规则", "50_名单与对标"}:
                records.append({
                    "source": str(source), "origin": origin, "layer": layer, "category": category,
                    "action": "skipped", "reason": "content_dlp:" + "|".join(hits), "sha256": digest,
                    "size_bytes": source.stat().st_size,
                })
                continue
        destination = unique_destination(package_root / layer / category / source.name, digest)
        if args.execute:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        package_hashes[digest] = str(destination)
        records.append({
            "source": str(source), "origin": origin, "layer": layer, "category": category,
            "action": "copied" if args.execute else "would_copy", "reason": "valuable_unique",
            "sha256": digest, "size_bytes": source.stat().st_size, "destination": str(destination),
        })
        if position % 100 == 0:
            print(f"processed_candidates={position}/{len(candidates)}", flush=True)

    suffix = "executed" if args.execute else "dry_run"
    safe_tag = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", args.report_tag)
    report_path = index_root / f"second_pass_import_{safe_tag}_{suffix}.csv"
    fields = ["source", "origin", "layer", "category", "action", "reason", "sha256", "size_bytes", "destination"]
    with report_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": suffix,
        "candidate_sources": len(seen_sources),
        "actions": dict(Counter(str(row["action"]) for row in records)),
        "reasons": dict(Counter(str(row["reason"]) for row in records)),
        "origins": dict(Counter(str(row["origin"]) for row in records if row["action"] in {"copied", "would_copy"})),
        "layers": dict(Counter(str(row["layer"]) for row in records if row["action"] in {"copied", "would_copy"})),
        "selected_bytes": sum(int(row.get("size_bytes", 0)) for row in records if row["action"] in {"copied", "would_copy"}),
        "report": str(report_path),
    }
    (index_root / f"second_pass_import_{safe_tag}_{suffix}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
