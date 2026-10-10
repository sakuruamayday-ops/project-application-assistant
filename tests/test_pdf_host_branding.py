from __future__ import annotations

import sys
from pathlib import Path

import pymupdf as fitz
import pytest

RUNTIME = Path(__file__).resolve().parents[1] / "skills/_runtime/gongchuang-branding"
sys.path.insert(0, str(RUNTIME / "scripts"))

from brand_config import public_identity
from delivery_gate import GateFailure, pdf_brand_watermark_rects, validate_pdf_document
from pdf_two_pass import brand_pdf_document


def document(pages=2):
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Synthetic report body page {index + 1}")
    return doc


def test_memory_branding_preserves_body_and_checks_every_page():
    with document() as doc:
        audit = brand_pdf_document(doc, variant="gold")
        assert len(audit) == 2
        assert all(row["watermark_action"] == "inserted" for row in audit)
        assert len(audit[0]["inserted_headers"]) == 2
        assert len(audit[1]["inserted_headers"]) == 1
        for index, page in enumerate(doc):
            assert f"Synthetic report body page {index + 1}" in page.get_text()
            assert public_identity()["document_header"] in page.get_text()
        assert validate_pdf_document(doc)["watermarks"] == 2
        with fitz.open(stream=doc.tobytes(), filetype="pdf") as reopened:
            assert validate_pdf_document(reopened)["watermarks"] == 2


def test_branding_does_not_duplicate_existing_watermark_or_header():
    with document() as doc:
        brand_pdf_document(doc, variant="gold")
        before = [page.get_text() for page in doc]
        audit = brand_pdf_document(doc, variant="gold")
        assert all(row["watermark_action"] == "preserved" for row in audit)
        assert all(row["inserted_headers"] == [] for row in audit)
        assert [page.get_text() for page in doc] == before
        assert validate_pdf_document(doc)["watermarks"] == 2


def test_duplicate_existing_watermarks_fail_instead_of_being_hidden():
    with document(1) as doc:
        audit = brand_pdf_document(doc, variant="gold")
        doc[0].insert_image(fitz.Rect(40, 40, 100, 100), filename=audit[0]["asset_path"])
        with pytest.raises(GateFailure, match="已有2个品牌水印"):
            brand_pdf_document(doc, variant="gold")


def test_text_identity_alone_is_not_a_watermark_receipt():
    with document(1) as doc:
        doc[0].insert_text((50, 50), public_identity()["document_header"], fontname="china-s")
        assert pdf_brand_watermark_rects(doc, doc[0]) == []
        with pytest.raises(GateFailure, match="水印数量为0"):
            validate_pdf_document(doc)


def test_shifted_existing_watermark_fails_placement_check():
    with document(1) as doc:
        asset = next((RUNTIME / "assets").glob("brand-*.png"))
        doc[0].insert_image(fitz.Rect(40, 40, 140, 140), filename=str(asset))
        with pytest.raises(GateFailure, match="未水平居中"):
            validate_pdf_document(doc)
