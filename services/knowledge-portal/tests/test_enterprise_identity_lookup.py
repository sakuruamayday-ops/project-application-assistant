import importlib.util
import sqlite3
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "enterprise_identity_lineage.py"
)
SPEC = importlib.util.spec_from_file_location("enterprise_identity_lineage", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_graph() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE enterprise_identity_lineage_nodes(
            node_id TEXT PRIMARY KEY,
            master_identity_key TEXT NOT NULL,
            node_type TEXT NOT NULL,
            node_value TEXT NOT NULL,
            normalized_value TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_lineage_edges(
            edge_id TEXT PRIMARY KEY,
            master_identity_key TEXT NOT NULL,
            from_node_id TEXT NOT NULL,
            to_node_id TEXT NOT NULL,
            from_node_type TEXT NOT NULL,
            to_node_type TEXT NOT NULL,
            from_value TEXT NOT NULL,
            to_value TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            unified_social_credit_code TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE enterprise_identity_resolution_audit(
            scope_key TEXT PRIMARY KEY, scope_label TEXT, total_subjects INTEGER,
            verified_subjects INTEGER, pending_subjects INTEGER,
            with_unified_social_credit_code INTEGER,
            without_unified_social_credit_code INTEGER,
            note TEXT, source TEXT
        );
        INSERT INTO enterprise_identity_resolution_audit VALUES
            ('all_identity_timeline','全部主体',2,1,1,1,1,'范围说明','焦糖知识库');
        INSERT INTO enterprise_identity_lineage_nodes VALUES
            ('subject:9133','9133','identity_subject','9133','9133','knowledge_verified','焦糖知识库'),
            ('current-name:9133','9133','current_name','现名科技有限公司','现名科技有限公司','knowledge_verified','焦糖知识库'),
            ('former-name:9133','9133','former_name','旧名科技有限公司','旧名科技有限公司','knowledge_verified','焦糖知识库'),
            ('credit-code:91330108MA2B254A2K','9133','unified_social_credit_code','91330108MA2B254A2K','91330108ma2b254a2k','knowledge_verified','焦糖知识库'),
            ('subject:name:待核验','name:待核验','identity_subject','name:待核验','name:待核验','pending_business_identity','焦糖知识库'),
            ('current-name:pending','name:待核验','current_name','待核验公司','待核验公司','pending_business_identity','焦糖知识库');
        INSERT INTO enterprise_identity_lineage_edges VALUES
            ('e1','9133','subject:9133','current-name:9133','identity_subject','current_name','9133','现名科技有限公司','current_name','91330108MA2B254A2K','knowledge_verified','焦糖知识库'),
            ('e2','9133','subject:9133','former-name:9133','identity_subject','former_name','9133','旧名科技有限公司','former_name','91330108MA2B254A2K','knowledge_verified','焦糖知识库'),
            ('e3','9133','subject:9133','credit-code:91330108MA2B254A2K','identity_subject','unified_social_credit_code','9133','91330108MA2B254A2K','unified_social_credit_code','91330108MA2B254A2K','knowledge_verified','焦糖知识库'),
            ('e4','name:待核验','subject:name:待核验','current-name:pending','identity_subject','current_name','name:待核验','待核验公司','current_name','','pending_business_identity','焦糖知识库');
        """
    )
    return connection


def test_lookup_by_former_name_returns_code_and_path():
    connection = make_graph()
    result = MODULE.lookup_identity_lineage(connection, "旧名科技有限公司")
    assert result["result_count"] == 1
    item = result["results"][0]
    assert item["matched_by"] == "former_name"
    assert item["unified_social_credit_code"] == "91330108MA2B254A2K"
    assert any(path["path_type"] == "matched_identity_path" for path in item["conflict_paths"])
    assert result["source"] == "焦糖知识库"


def test_lookup_by_code_is_exact_and_does_not_expose_provider_fields():
    connection = make_graph()
    result = MODULE.lookup_identity_lineage(connection, "91330108MA2B254A2K")
    assert result["query_type"] == "unified_social_credit_code"
    assert result["result_count"] == 1
    assert result["results"][0]["current_name"] == "现名科技有限公司"
    assert "tyc_company_id" not in result["results"][0]


def test_pending_name_exposes_missing_code_conflict_without_guessing():
    connection = make_graph()
    result = MODULE.lookup_identity_lineage(connection, "待核验公司")
    item = result["results"][0]
    assert item["unified_social_credit_code"] == []
    assert any(
        path["path_type"] == "missing_unified_social_credit_code"
        for path in item["conflict_paths"]
    )
    assert result["coverage"]["all_identity_timeline"]["pending_subjects"] == 1
