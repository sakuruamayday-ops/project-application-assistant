#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--page-inventory", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    with args.report.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["status"] == "ocr_required"]
    page_inventory = json.loads(args.page_inventory.read_text(encoding="utf-8"))
    page_by_source = {
        item["source"]: item for item in page_inventory.get("documents", [])
    }
    error_by_source = {
        item["source"]: item["error"] for item in page_inventory.get("errors", [])
    }
    knowledge_root = args.report.parents[2] / "_云端知识库"
    sha_counts = Counter(row["sha256"] for row in rows)
    detail_rows = []
    for row in rows:
        source = knowledge_root / row["relative_path"]
        page = page_by_source.get(str(source), {})
        detail_rows.append(
            {
                "一级目录": Path(row["relative_path"]).parts[0],
                "相对路径": row["relative_path"],
                "页数": page.get("pages", ""),
                "文件大小字节": page.get("size_bytes", source.stat().st_size if source.exists() else ""),
                "SHA256": row["sha256"],
                "同哈希文件数": sha_counts[row["sha256"]],
                "读取状态": "PDF结构异常" if str(source) in error_by_source else "可读取",
                "异常原因": error_by_source.get(str(source), ""),
            }
        )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail_rows[0]))
        writer.writeheader()
        writer.writerows(detail_rows)

    category_counts = Counter(row["一级目录"] for row in detail_rows)
    total_size = sum(int(row["文件大小字节"] or 0) for row in detail_rows)
    readable_pages = sum(int(row["页数"] or 0) for row in detail_rows)
    unique_count = len(sha_counts)
    duplicate_rows = len(detail_rows) - unique_count
    malformed_count = sum(row["读取状态"] != "可读取" for row in detail_rows)
    lines = [
        "# 625份待OCR资料盘点",
        "",
        "盘点日期：2026-07-21",
        "",
        "## 总体情况",
        "",
        f"- 待OCR路径：{len(detail_rows)}条。",
        f"- 去重后文件：{unique_count}份，重复路径：{duplicate_rows}条。",
        f"- 文件体积：{total_size / 1_000_000_000:.2f} GB。",
        f"- 可读取PDF已识别页数：至少{readable_pages:,}页。",
        f"- PDF结构异常或页数暂不可读：{malformed_count}份，需先修复或重导出。",
        "- 文件类型：624份以 `.pdf` 结尾，另有1份未带PDF扩展名但实际为PDF。",
        "",
        "## 目录构成",
        "",
        "| 一级目录 | 数量 | 主要内容 | 建议优先级 |",
        "|---|---:|---|---|",
        f"| `10_政策与目录` | {category_counts['10_政策与目录']} | 企策顾问申报通知96份、公示公告91份，以及首版次、数字化、浙江制造精品等政策附件 | 高，先处理现行政策、名单和当期通知 |",
        f"| `20_申报指南与规则` | {category_counts['20_申报指南与规则']} | 优质中小企业梯度培育、技术中心、工业设计中心、加计扣除、人才和涉农指南 | 高，先核验现行效力再OCR |",
        f"| `40_内部培训与方法` | {category_counts['40_内部培训与方法']} | 谈单资料121份、答辩与培训83份、专精特新方法11份、加计扣除8份 | 中，方法论优先，合同和单家企业附件降级 |",
        f"| `60_申报案例与建设方案` | {category_counts['60_申报案例与建设方案']} | 技术中心103份、优质中小企业31份、技改与未来工厂24份、首版次14份等案例附件 | 中低，优先申请书与建设方案，合同、发票、审计附件不建议批量OCR |",
        "",
        "## 重要说明",
        "",
        "- 这625条是“当前没有可靠可检索正文”的路径，不代表625份都值得同等优先OCR。",
        "- 其中包含合同、发票、审计报告、认证证书、人员名单和企业附件，与此前确定的知识库排除口径存在交叉；正式OCR前应按用途二次筛选。",
        "- 完整逐文件路径、页数、哈希重复数和异常原因见同目录CSV。",
        "- OCR完成后仍需抽样复核名单中的企业名称、序号、金额、日期和表格列。",
    ]
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
