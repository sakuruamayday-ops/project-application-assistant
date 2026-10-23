"""Runtime regressions for the framework and document dependency upgrade."""

from contextlib import closing
import sqlite3

import pytest

from test_client_reports import setup


@pytest.mark.parametrize("send_blank_fields", [True, False])
def test_optional_metadata_forms_allow_blank_and_keep_csrf_and_evidence_checks(tmp_path, send_blank_fields):
    portal, client, _ = setup(tmp_path)
    login = client.post("/login", data={"username": "owner", "password": "synthetic-password-123"},
                        follow_redirects=False)
    csrf = portal.session_user(login.cookies[portal.SESSION_COOKIE])[0]["csrf_token"]
    alias = {
        "raw_project_name": "小巨人测试资料", "canonical_project_name": "空值兼容项目",
        "csrf_token": csrf,
    }
    if send_blank_fields:
        alias.update(region="", start_year="", end_year="", note="")
    assert client.post("/admin/metadata-review/aliases/preview", data=alias).status_code == 200
    assert client.post(
        "/admin/metadata-review/aliases/preview", data={**alias, "csrf_token": "invalid"},
    ).status_code == 403
    assert client.post("/admin/metadata-review/aliases", data=alias, follow_redirects=False).status_code == 303

    with closing(sqlite3.connect(portal.CONTENT_DATABASE_PATH)) as connection:
        document_id = connection.execute("SELECT id FROM documents WHERE source_key='doc-policy'").fetchone()[0]
        queue_id = connection.execute(
            "INSERT INTO policy_verification_queue(document_id,reason,priority,status,created_at,updated_at) "
            "VALUES (?,'空值兼容测试','high','pending',?,?)",
            (document_id, "2026-10-23T00:00:00+00:00", "2026-10-23T00:00:00+00:00"),
        ).lastrowid
        connection.commit()
    policy = {"queue_id": queue_id, "review_status": "rejected", "csrf_token": csrf}
    if send_blank_fields:
        policy.update(official_source_url="", official_document_title="", official_published_at="",
                      validity_status="", verification_note="")
    assert client.post("/admin/metadata-review/policies/preview", data=policy).status_code == 200
    missing_evidence = client.post(
        "/admin/metadata-review/policies/preview", data={**policy, "review_status": "verified"},
    )
    assert missing_evidence.status_code == 422
    assert "官方网站来源" in missing_evidence.json()["detail"]
    assert client.post("/admin/metadata-review/policies", data=policy, follow_redirects=False).status_code == 303


def test_pdf_extract_worker_reads_current_pdf_without_layout_inference(tmp_path, monkeypatch):
    import pymupdf
    from pypdf import PdfReader
    from scripts.build_knowledge_content_index import extract_pdf, extract_pdf_isolated

    path = tmp_path / "dependency-runtime.pdf"
    with pymupdf.open() as document:
        for number in range(12):
            page = document.new_page()
            page.insert_text((36, 72), f"PDF dependency runtime page {number + 1} fixture 20261023")
        document.save(path)

    def unexpected_layout(*args, **kwargs):
        raise AssertionError("classic text extraction must not invoke layout inference")

    monkeypatch.setattr(pymupdf, "_get_layout", unexpected_layout)
    assert "page 12 fixture 20261023" in extract_pdf(path)
    assert len(PdfReader(path).pages) == 12
    assert "page 12 fixture 20261023" in extract_pdf_isolated(path)
