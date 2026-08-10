#!/usr/bin/env python3
import csv
import hashlib
import json
import re
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "references" / "ipc-snapshots"

HANGZHOU_CODES = """
A01C A01D A61B A61F A61L A61M A63F B01D B01F B01L B02C B05B B07B B07C B08B
B21D B23B B23D B23K B23P B23Q B24B B25B B25J B26D B29B B29C B30B B33Y B60G
B60N B60P B60R B60S B60T B60W B61L B63B B63C B63H B64C B64D B64U B65B B65D
B65G B65H B66B B66C B66F B81B B81C B82Y C07B C12M E02B E02F E21B F01D F02C
F03B F03D F04B F04D F15B F16B F16C F16D F16F F16H F16J F16K F16L F16M F17C
F17D F23D F24H F28B F28D F28F G01D G01F G01L G01M G01N G01Q G01T G01V G02B
G02F G03F G04F G05B G05D G05F G06F G06N G06Q G06T G06V G07B G07F G09C G09F
G16B G16C G16Y H01L H01Q H01S H02G H03H H04L H04N H04Q H04S H04W H05G H05H
H10B H10K H10N
""".split()


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_zhejiang(pdf_path):
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text("text") for page in doc)
    pairs = re.findall(
        r"(?m)^\s*(\d{1,3})\s*\n\s*([A-H][0-9]{2}[A-Z])\s*$", text
    )
    return [code for _, code in pairs]


def main():
    SNAP.mkdir(parents=True, exist_ok=True)
    zhejiang_pdf = SNAP / "zhejiang-ipc-2024-07-11-official.pdf"
    hangzhou_management = (
        SNAP / "hangzhou-preexam-management-2025-revised-official.docx"
    )
    zhejiang_codes = extract_zhejiang(zhejiang_pdf)
    if len(zhejiang_codes) != 167 or len(set(zhejiang_codes)) != 167:
        raise SystemExit("浙江 IPC 解析结果不是 167 个唯一小类")
    if len(HANGZHOU_CODES) != 123 or len(set(HANGZHOU_CODES)) != 123:
        raise SystemExit("杭州 IPC 重建结果不是 123 个唯一小类")

    centers = {
        "浙江省知识产权保护中心": {
            "release_date": "2024-07-11",
            "industries": ["生物", "绿色低碳", "新一代信息技术"],
            "ipc_count": 167,
            "ipc_subclasses": zhejiang_codes,
            "artifact": zhejiang_pdf.name,
            "artifact_sha256": sha256(zhejiang_pdf),
            "artifact_status": "official_original_archived",
            "source_page": "https://yushen.zjamr.zj.gov.cn/web/details/dcfc3ad0ac674ddd8222302f54447d25.html",
            "attachment_url": "https://zjippc.org.cn/web/files/2024-07-11/e13f0bfc95a843949d649c76dbddb0e0.pdf",
        },
        "杭州市知识产权保护中心": {
            "release_date": "2024-07-23",
            "attachment_object_date_in_path": "2024-07-22",
            "industries": ["数字经济", "高端装备制造"],
            "ipc_count": 123,
            "ipc_subclasses": HANGZHOU_CODES,
            "artifact": None,
            "artifact_sha256": None,
            "artifact_status": "official_url_http_403; canonical_index_rebuilt_from_official_search_index",
            "source_page": "https://scjg.hangzhou.gov.cn/art/2025/2/20/art_1693481_58926968.html",
            "attachment_url": "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3246/site/attach/0/2407221736322339.pdf",
            "management_artifact": hangzhou_management.name,
            "management_artifact_sha256": sha256(hangzhou_management),
        },
    }
    index_path = SNAP / "dual-center-ipc-index.json"
    index_payload = {
        "schema_version": "1.0",
        "generated_at": "2026-07-26",
        "national_ipc_baseline": "IPC 2026.01, effective 2026-01-01",
        "centers": centers,
    }
    index_path.write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (SNAP / "dual-center-ipc-comparison.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ipc_subclass",
                "zhejiang",
                "hangzhou",
                "overlap",
                "zhejiang_release_date",
                "hangzhou_release_date",
            ],
        )
        writer.writeheader()
        for code in sorted(set(zhejiang_codes) | set(HANGZHOU_CODES)):
            in_zj = code in zhejiang_codes
            in_hz = code in HANGZHOU_CODES
            writer.writerow(
                {
                    "ipc_subclass": code,
                    "zhejiang": int(in_zj),
                    "hangzhou": int(in_hz),
                    "overlap": int(in_zj and in_hz),
                    "zhejiang_release_date": "2024-07-11",
                    "hangzhou_release_date": "2024-07-23",
                }
            )

    manifest = {
        "generated_at": "2026-07-26",
        "files": {
            zhejiang_pdf.name: {
                "sha256": sha256(zhejiang_pdf),
                "status": "official_original",
            },
            hangzhou_management.name: {
                "sha256": sha256(hangzhou_management),
                "status": "official_original",
            },
            index_path.name: {
                "sha256": sha256(index_path),
                "status": "canonical_structured_index",
            },
            "dual-center-ipc-comparison.csv": {
                "sha256": sha256(SNAP / "dual-center-ipc-comparison.csv"),
                "status": "generated_comparison",
            },
        },
        "hangzhou_official_pdf": {
            "url": centers["杭州市知识产权保护中心"]["attachment_url"],
            "sha256": None,
            "retrieval_status": "HTTP 403 on 2026-07-26",
            "follow_up": "恢复下载后归档原件、补 SHA-256，并与 123 项结构化索引逐项比对",
        },
    }
    (SNAP / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "zhejiang": len(zhejiang_codes),
                "hangzhou": len(HANGZHOU_CODES),
                "overlap": len(set(zhejiang_codes) & set(HANGZHOU_CODES)),
                "index_sha256": sha256(index_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
