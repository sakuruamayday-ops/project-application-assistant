from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".wps",
    ".md",
    ".txt",
    ".csv",
}
SENSITIVE_TERMS = (
    "身份证",
    "护照",
    "手机号",
    "通讯录",
    "银行流水",
    "银行卡",
    "工资",
    "社保",
    "劳动合同",
    "审计报告",
    "纳税申报",
    "发票",
    "销售合同",
    "采购合同",
    "客户名单",
    "人员名单",
    "研发人员清单",
    "营业执照",
    "学历证书",
    "毕业证",
    "职称证书",
    "专利证书",
    "签章",
    "盖章",
    "财务尽调",
    "市场占有率证明",
    "产能证明",
    "申请受理通知书",
    "检测报告",
    "鉴定证书",
    "鉴定过程",
    "整套材料",
    "经济效益分析报告",
    "投产条件报告",
    "自主知识产权实施情况报告",
    "试制工作和技术总结报告",
    "佐证材料",
    "申报书",
    "申请书",
    "终稿",
    "上报稿",
    "提交稿",
    "装订材料",
    "已填写",
    "有限公司",
    "股份有限公司",
)
EXCLUDED_TERMS = (
    "副本",
    "复件",
    "备份",
    "缓存",
    "desktop-attachments",
    "node_modules",
    "厦门特房国际设计",
    "东光科技",
    "浙江宏都",
    "远望-行业",
    "证券-",
    "证券－",
    "专题报告",
    "行业深度报告",
    "产业报告",
    "全国细分市场",
    "浙江省科技型中小企业证书(1)",
    "案例：",
)
SOURCE_RULES = (
    ("专精特新文件", "10_政策与目录/专精特新与小巨人", None),
    ("申报信息指引/00-常见项目申报管理办法、规范（原文）", "10_政策与目录/综合政策", None),
    ("申报信息指引/03-浙江省研发中心申报指引及实务", "20_申报指南与规则/企业研发机构", None),
    ("申报信息指引/04-浙江省专精特新申报指引及实务", "20_申报指南与规则/专精特新与小巨人", None),
    ("申报信息指引/05-浙江省重点专精特新", "10_政策与目录/专精特新与小巨人", None),
    ("申报信息指引/浙江制造精品", "20_申报指南与规则/浙江制造精品", None),
    ("申报信息指引/浙江省工业设计中心", "20_申报指南与规则/工业设计中心", None),
    ("申报信息指引/未来工厂、智能制造", "20_申报指南与规则/未来工厂与智能制造", None),
    ("申报信息指引/浙江省企业技术中心", "20_申报指南与规则/企业技术中心", None),
    ("申报信息指引/浙江省专利示范企业", "20_申报指南与规则/知识产权项目", 1),
    ("申报信息指引/专利试点示范", "20_申报指南与规则/知识产权项目", 1),
    ("申报信息指引/浙江省重点计划", "20_申报指南与规则/科技计划", None),
    ("申报信息指引/杭州市重点计划", "20_申报指南与规则/科技计划", None),
    ("申报信息指引/浙江省工业新产品/新产品/新产品试制计划", "30_空白模板/工业新产品", 1),
    ("申报信息指引/浙江省科技型中小企业", "20_申报指南与规则/科技型中小企业", None),
    ("申报信息指引/全省重点实验室申报资料包", "20_申报指南与规则/重点实验室", None),
    ("申报信息指引/学习PPT（重要！）", "40_内部培训与方法/培训课件", None),
    ("高新制度/制度文件", "30_空白模板/高新制度", None),
    ("申报信息指引/项目申报、服务辅助信息/标准化服务动作", "40_内部培训与方法/标准化服务", None),
    ("申报信息指引/项目申报、服务辅助信息/杭州申报证书导出流程、证书模板", "30_空白模板/系统操作", None),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="精选石晨硬盘资料并去重导入云端知识库目录")
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_SOURCE_ROOT", Path.cwd() / "source-materials")))
    parser.add_argument("--knowledge-root", type=Path, default=Path(os.environ.get("JIAOTANG_LOCAL_KNOWLEDGE_ROOT", Path.cwd() / "knowledge")))
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_existing_hashes(knowledge_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    manifest = knowledge_root / "_云端迁移索引" / "manifest.jsonl"
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("sha256"):
                hashes.setdefault(str(record["sha256"]), str(record["source_path"]))
    return hashes


def rejection_reason(path: Path) -> str | None:
    text = str(path).lower()
    if path.name.startswith("._") or path.name.startswith("~$") or path.name == ".DS_Store":
        return "system_or_temporary"
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return "unsupported_or_archive"
    for term in SENSITIVE_TERMS:
        if term.lower() not in text:
            continue
        if term in {"申报书", "申请书"} and any(marker in text for marker in ("模板", "空白", "样表")):
            continue
        return "sensitive_or_customer_specific"
    if any(term.lower() in text for term in EXCLUDED_TERMS):
        return "duplicate_or_low_value_name"
    return None


def unique_destination(destination: Path, digest: str) -> Path:
    if not destination.exists():
        return destination
    if sha256_file(destination) == digest:
        return destination
    return destination.with_name(f"{destination.stem}__{digest[:8]}{destination.suffix}")


def main() -> None:
    args = parse_args()
    source_root = args.source.expanduser().resolve()
    knowledge_root = args.knowledge_root.expanduser().resolve()
    destination_root = knowledge_root / "_云端知识库"
    report_root = knowledge_root / "_云端迁移索引"
    existing_hashes = load_existing_hashes(knowledge_root)
    records: list[dict[str, object]] = []

    for source_relative, destination_category, max_depth in SOURCE_RULES:
        selection_root = source_root / source_relative
        if not selection_root.exists():
            records.append(
                {
                    "source": str(selection_root),
                    "category": destination_category,
                    "action": "missing_source",
                    "reason": "configured source does not exist",
                }
            )
            continue
        for source in selection_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(selection_root)
            if max_depth is not None and len(relative.parts) > max_depth:
                records.append(
                    {
                        "source": str(source),
                        "category": destination_category,
                        "action": "skipped",
                        "reason": "outside_curated_depth",
                        "size_bytes": source.stat().st_size,
                    }
                )
                continue
            reason = rejection_reason(source)
            if reason:
                records.append(
                    {
                        "source": str(source),
                        "category": destination_category,
                        "action": "skipped",
                        "reason": reason,
                        "size_bytes": source.stat().st_size,
                    }
                )
                continue
            digest = sha256_file(source)
            existing = existing_hashes.get(digest)
            if existing:
                records.append(
                    {
                        "source": str(source),
                        "category": destination_category,
                        "action": "existing_duplicate",
                        "reason": "same_sha256",
                        "sha256": digest,
                        "size_bytes": source.stat().st_size,
                        "destination_or_existing": existing,
                    }
                )
                continue
            destination = unique_destination(destination_root / destination_category / relative, digest)
            if args.execute:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            existing_hashes[digest] = str(destination)
            records.append(
                {
                    "source": str(source),
                    "category": destination_category,
                    "action": "copied" if args.execute else "would_copy",
                    "reason": "curated_unique",
                    "sha256": digest,
                    "size_bytes": source.stat().st_size,
                    "destination_or_existing": str(destination),
                }
            )

    report_root.mkdir(parents=True, exist_ok=True)
    suffix = "executed" if args.execute else "dry_run"
    csv_path = report_root / f"shichen_import_{suffix}.csv"
    fieldnames = [
        "source",
        "category",
        "action",
        "reason",
        "sha256",
        "size_bytes",
        "destination_or_existing",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    action_counts = Counter(str(record["action"]) for record in records)
    copied_bytes = sum(
        int(record.get("size_bytes", 0))
        for record in records
        if record["action"] in {"copied", "would_copy"}
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": suffix,
        "source_root": str(source_root),
        "destination_root": str(destination_root),
        "actions": dict(action_counts),
        "selected_unique_bytes": copied_bytes,
        "selected_unique_gib": round(copied_bytes / 1024**3, 3),
        "report": str(csv_path),
    }
    (report_root / f"shichen_import_{suffix}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
