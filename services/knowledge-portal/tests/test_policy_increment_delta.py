from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature

from scripts.policy_increment_delta import (
    PolicyIncrementError,
    authoritative_list_triggers,
    build_base_anchor,
    generate_key,
    manifest_verification,
    measure_sqlite_pages,
    parse_first_rsync_bytes,
    verify_package,
    verify_base_anchor,
)


def test_authoritative_list_trigger_ignores_negating_notes_and_city_application() -> None:
    handoff = {
        "records": [
            {
                "metadata": {
                    "formal_title": "关于公示浙江省科技型中小企业名单的通知",
                    "project_name": "浙江省科技型中小企业名单",
                    "file_type": "公示公告",
                    "notes": "非浙江省专精特新中小企业名单",
                }
            },
            {
                "metadata": {
                    "formal_title": "关于组织开展宁波市首版次软件产品申报工作的通知",
                    "project_name": "宁波市首版次软件产品申报",
                    "file_type": "申报通知",
                    "notes": "不是浙江省首版次软件产品名单",
                }
            },
        ]
    }
    assert authoritative_list_triggers(handoff) == []


def test_authoritative_list_trigger_detects_real_list_title() -> None:
    handoff = {
        "records": [
            {
                "metadata": {
                    "formal_title": "关于公布2026年度浙江省专精特新中小企业名单的通知",
                    "project_name": "2026年度浙江省专精特新中小企业名单",
                    "file_type": "结果公布",
                    "notes": "",
                }
            }
        ]
    }
    assert authoritative_list_triggers(handoff) == ["浙江省专精特新中小企业"]


def test_manifest_verification_requires_exact_cardinality() -> None:
    expected = [
        {
            "record_key": "one",
            "role": "official_text",
            "expected_manifest_path": "政策/通知.md",
            "sha256": "ab" * 32,
            "size_bytes": 12,
            "match_rule": "exactly_one:path+sha256+size_bytes",
        }
    ]
    exact = manifest_verification(
        expected,
        [{"relative_path": "政策/通知.md", "sha256": "ab" * 32, "size_bytes": 12}],
    )
    assert exact["all_exact"] is True
    assert exact["counts"]["exact"] == 1
    duplicate = manifest_verification(
        expected,
        [
            {"relative_path": "政策/通知.md", "sha256": "ab" * 32, "size_bytes": 12},
            {"relative_path": "政策/通知.md", "sha256": "ab" * 32, "size_bytes": 12},
        ],
    )
    assert duplicate["all_exact"] is False
    assert duplicate["counts"]["duplicate"] == 1


def test_generate_key_refuses_overwrite(tmp_path: Path) -> None:
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    result = generate_key(private, public)
    assert result["algorithm"] == "Ed25519"
    assert private.stat().st_mode & 0o777 == 0o600
    with pytest.raises(PolicyIncrementError, match="拒绝覆盖"):
        generate_key(private, public)


def test_signed_base_anchor_verifies_exact_files(tmp_path: Path) -> None:
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    generate_key(private, public)
    database = tmp_path / "base.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sample(value TEXT)")
    connection.commit()
    connection.close()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("", encoding="utf-8")
    result = build_base_anchor(database, manifest, tmp_path / "anchor", private)
    verified = verify_base_anchor(tmp_path / "anchor", database, manifest, public)
    assert verified["signature"]["chain_sha256"] == result["signature"]["chain_sha256"]
    manifest.write_text("changed\n", encoding="utf-8")
    with pytest.raises(PolicyIncrementError, match="manifest 已变化"):
        verify_base_anchor(tmp_path / "anchor", database, manifest, public)


def test_verify_package_rejects_tampered_payload(tmp_path: Path) -> None:
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    generate_key(private, public)
    package = tmp_path / "package"
    package.mkdir()
    payload = package / "delta_payload.json"
    payload.write_text("{}\n", encoding="utf-8")
    manifest = {
        "format": "jiaotang-policy-sqlite-delta-v1",
        "schema_version": "1.0",
        "payload_sha256": __import__("hashlib").sha256(payload.read_bytes()).hexdigest(),
        "handoff_files": {},
    }
    from scripts.policy_increment_delta import sign_delta_manifest, write_json

    write_json(package / "delta_manifest.json", manifest)
    sign_delta_manifest(package, private, None)
    verify_package(package, public)
    payload.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(PolicyIncrementError, match="payload"):
        verify_package(package, public)


def test_verify_package_rejects_wrong_public_key(tmp_path: Path) -> None:
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    wrong_private = tmp_path / "wrong-private.pem"
    wrong_public = tmp_path / "wrong-public.pem"
    generate_key(private, public)
    generate_key(wrong_private, wrong_public)
    package = tmp_path / "package"
    package.mkdir()
    payload = package / "delta_payload.json"
    payload.write_text("{}\n", encoding="utf-8")
    from scripts.policy_increment_delta import sha256_file, sign_delta_manifest, write_json

    write_json(
        package / "delta_manifest.json",
        {
            "format": "jiaotang-policy-sqlite-delta-v1",
            "schema_version": "1.0",
            "payload_sha256": sha256_file(payload),
            "handoff_files": {},
        },
    )
    sign_delta_manifest(package, private, None)
    with pytest.raises(PolicyIncrementError, match="key_id"):
        verify_package(package, wrong_public)


def test_measure_sqlite_pages_reports_changed_pages(tmp_path: Path) -> None:
    base = tmp_path / "base.sqlite3"
    candidate = tmp_path / "candidate.sqlite3"
    connection = sqlite3.connect(base)
    connection.execute("CREATE TABLE sample(value TEXT)")
    connection.execute("INSERT INTO sample VALUES (?)", ("baseline",))
    connection.commit()
    connection.close()
    candidate.write_bytes(base.read_bytes())
    connection = sqlite3.connect(candidate)
    connection.execute("INSERT INTO sample VALUES (?)", ("candidate",))
    connection.commit()
    connection.close()
    result = measure_sqlite_pages(base, candidate)
    assert result["page_size"] in {4096, 8192, 16384}
    assert result["total_changed_pages"] >= 1
    assert result["changed_page_bytes"] >= result["page_size"]


def test_parse_rsync_supports_openrsync_labels() -> None:
    output = (
        "Unmatched data: 28418048 B\nMatched data: 3314823168 B\n"
        "Total sent: 31,000,000 bytes\nTotal received: 20,000,000 bytes\n"
    )
    assert parse_first_rsync_bytes(output, ("Literal data", "Unmatched data")) == 28_418_048
    assert parse_first_rsync_bytes(output, ("Total bytes sent", "Total sent")) == 31_000_000
    assert parse_first_rsync_bytes(output, ("Total bytes received", "Total received")) == 20_000_000
