import importlib.util
import json
import sqlite3
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_enterprise_identity_lineage.py"
)
SPEC = importlib.util.spec_from_file_location("identity_lineage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            current_name TEXT NOT NULL,
            verification_status TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_names(
            id INTEGER PRIMARY KEY,
            identity_key TEXT NOT NULL,
            alias_name TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT '',
            valid_to TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO enterprise_identity_profiles VALUES(
            '91330108MA2B254A2K', '91330108MA2B254A2K', '现名科技有限公司', 'knowledge_verified'
        );
        INSERT INTO enterprise_identity_names(
            identity_key,alias_name,alias_type
        ) VALUES ('91330108MA2B254A2K','曾用名科技有限公司','former_name');
        """
    )
    connection.commit()
    connection.close()


def test_lineage_projection_contains_four_identity_layers_and_public_source(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    output = tmp_path / "output"
    snapshot = tmp_path / "snapshot.jsonl"
    make_database(database)
    snapshot.write_text(
        json.dumps(
            {
                "identity_key": "91330108MA2B254A2K",
                "master_identity_key": "name:曾用名科技有限公司",
                "merged_master_identity_keys": [
                    "name:曾用名科技有限公司",
                    "91330108MA2B254A2K",
                ],
                "unified_social_credit_code": "91330108MA2B254A2K",
                "current_name": "现名科技有限公司",
                "former_names": ["旧注册名科技有限公司"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = MODULE.build_lineage_rows(database, snapshot)
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "焦糖知识库"
    assert row["master_identity_key"] == "name:曾用名科技有限公司"
    assert row["former_names"] == ["曾用名科技有限公司", "旧注册名科技有限公司"]
    assert row["unified_social_credit_code"] == "91330108MA2B254A2K"
    assert {edge["relation_type"] for edge in row["edges"]} == {
        "current_name",
        "former_name",
        "unified_social_credit_code",
        "merged_subject",
    }
    assert {node["source"] for node in row["nodes"]} == {"焦糖知识库"}
    assert {edge["source"] for edge in row["edges"]} == {"焦糖知识库"}
    public_rows = MODULE.public_projection_rows(rows)
    assert len(public_rows) == len(row["edges"])
    assert all(item["source"] == "焦糖知识库" for item in public_rows)
    assert all("nodes" not in item and "edges" not in item for item in public_rows)


def test_resolution_audit_exempts_two_projects_without_hiding_other_requirements(
    tmp_path: Path,
):
    database = tmp_path / "coverage.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE enterprise_identity_profiles(
            identity_key TEXT PRIMARY KEY,
            unified_social_credit_code TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            recognition_projects_json TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO enterprise_identity_profiles VALUES(?,?,?,?)",
        [
            ("a", "", "pending_business_identity", json.dumps(["浙江制造精品"])),
            ("b", "", "pending_business_identity", json.dumps(["地方科技小巨人企业"])),
            (
                "c",
                "",
                "pending_business_identity",
                json.dumps(["地方科技小巨人企业", "浙江省专精特新中小企业"]),
            ),
        ],
    )
    connection.commit()
    connection.close()

    rows = {
        row["scope_key"]: row
        for row in MODULE.build_resolution_audit(database, [], None)
    }

    assert rows["pending_identity_verification_required"]["pending_subjects"] == 1
    assert "pending_project:浙江制造精品" not in rows
    assert "pending_project:地方科技小巨人企业" not in rows
    assert rows["pending_project:浙江省专精特新中小企业"]["pending_subjects"] == 1
    assert rows["verification_exempt_project:浙江制造精品"]["pending_subjects"] == 0
    assert rows["verification_exempt_project:地方科技小巨人企业"]["pending_subjects"] == 0


def test_database_graph_and_alias_projection_are_written_with_unified_source(tmp_path: Path):
    database = tmp_path / "knowledge.sqlite3"
    output = tmp_path / "output"
    make_database(database)
    output.mkdir()
    (output / "浙江省企业名称历史.jsonl").write_text(
        json.dumps({"identity_key": "x", "alias_name": "旧", "source": "内部文件名"})
        + "\n",
        encoding="utf-8",
    )
    rows = MODULE.build_lineage_rows(database, None)
    assert MODULE.sanitize_public_alias_projection(output) == 1
    node_count, edge_count = MODULE.write_database_graph(database, rows)
    assert node_count >= 4
    assert edge_count >= 3
    alias = json.loads((output / "浙江省企业名称历史.jsonl").read_text(encoding="utf-8"))
    assert alias["source"] == "焦糖知识库"
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT COUNT(*) FROM enterprise_identity_lineage_edges"
    ).fetchone()[0] == edge_count
    assert connection.execute(
        "SELECT DISTINCT source FROM enterprise_identity_lineage_edges"
    ).fetchall() == [("焦糖知识库",)]
    connection.close()


def test_public_profile_projection_drops_provider_identifier(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "浙江省企业身份档案.jsonl").write_text(
        json.dumps(
            {
                "identity_key": "x",
                "tyc_company_id": "provider-only",
                "identity_source": "search_companies|get_company_basic_profile",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert MODULE.sanitize_public_profile_projection(output) == 1
    row = json.loads(
        (output / "浙江省企业身份档案.jsonl").read_text(encoding="utf-8")
    )
    assert "tyc_company_id" not in row
    assert row["identity_source"] == "焦糖知识库"
