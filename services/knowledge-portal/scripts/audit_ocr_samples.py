from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path


YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def main() -> None:
    parser = argparse.ArgumentParser(description="抽检OCR伴生Markdown与名单结构质量")
    parser.add_argument("--extraction-report", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--priority-audit", type=Path, required=True)
    parser.add_argument("--list-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    extraction_rows = read_csv(args.extraction_report)
    pending_rows = [row for row in extraction_rows if row.get("status") == "ocr_required"]
    companion_rows: list[dict[str, object]] = []
    for row in pending_rows:
        relative_path = Path(row["relative_path"])
        markdown_path = (args.knowledge_root / relative_path).with_suffix(".md")
        if not markdown_path.is_file():
            continue
        text = markdown_path.read_text(encoding="utf-8", errors="replace")
        title = relative_path.stem
        title_tokens = [character for character in title if character.isalnum()]
        title_coverage = (
            sum(character in text for character in title_tokens) / len(title_tokens)
            if title_tokens
            else 1.0
        )
        years = YEAR_PATTERN.findall(title)
        companion_rows.append(
            {
                "relative_path": relative_path.as_posix(),
                "markdown_path": markdown_path.relative_to(args.knowledge_root).as_posix(),
                "markdown_chars": len(text),
                "replacement_characters": text.count("�"),
                "title_coverage": round(title_coverage, 4),
                "filename_years_preserved": all(year in text for year in years),
                "healthy": len(text.strip()) >= 40 and text.count("�") == 0 and title_coverage >= 0.5,
            }
        )

    priority_rows = read_csv(args.priority_audit)
    priority_success = [row for row in priority_rows if row.get("处理状态") == "ocr_success"]
    list_rows = read_csv(args.list_audit)
    list_success = [row for row in list_rows if row.get("处理状态") == "ocr_success"]
    list_failures = [
        row
        for row in list_success
        if any(str(row.get(field) or "").strip() for field in ("跳号", "重复号", "可疑企业名"))
    ]

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reported_ocr_required": len(pending_rows),
        "ocr_companion_markdown_found": len(companion_rows),
        "true_pending_after_companion_reconciliation": len(pending_rows) - len(companion_rows),
        "companion_samples_healthy": sum(bool(row["healthy"]) for row in companion_rows),
        "priority_ocr_success_documents": len(priority_success),
        "priority_ocr_pages": sum(int(row.get("页数") or 0) for row in priority_success),
        "priority_ocr_markdown_characters": sum(int(row.get("Markdown字符数") or 0) for row in priority_success),
        "list_ocr_success_documents": len(list_success),
        "list_ocr_pages": sum(int(row.get("页数") or 0) for row in list_success),
        "list_ocr_table_rows": sum(int(row.get("表格数据行") or 0) for row in list_success),
        "list_structural_failures": len(list_failures),
        "priority_audit_available": args.priority_audit.is_file(),
        "list_audit_available": args.list_audit.is_file(),
        "audit_boundary": "结构门禁抽检，不等同于逐字符人工真值校对；企业名称与序号仍需周期性视觉复核。",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps({"summary": summary, "companions": companion_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown = [
        "# OCR资料抽检报告",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 原报告待OCR：{summary['reported_ocr_required']}份",
        f"- 已有Markdown伴生文本：{summary['ocr_companion_markdown_found']}份",
        f"- 伴生文本归并后真正待OCR：{summary['true_pending_after_companion_reconciliation']}份",
        f"- 伴生文本结构门禁通过：{summary['companion_samples_healthy']}份",
        f"- 优先OCR成功样本：{summary['priority_ocr_success_documents']}份，{summary['priority_ocr_pages']}页，{summary['priority_ocr_markdown_characters']}字符",
        f"- 名单OCR成功样本：{summary['list_ocr_success_documents']}份，{summary['list_ocr_pages']}页，{summary['list_ocr_table_rows']}行",
        f"- 名单跳号、重复号或可疑企业名异常：{summary['list_structural_failures']}份",
        f"- 历史优先OCR审计表：{'已读取' if summary['priority_audit_available'] else '未挂载，按零样本处理'}",
        f"- 历史名单OCR审计表：{'已读取' if summary['list_audit_available'] else '未挂载，按零样本处理'}",
        "",
        "## 结论边界",
        "",
        summary["audit_boundary"],
        "原始PDF继续保留作证据，Markdown作为检索伴生文本，不替代原件。",
    ]
    args.output.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
