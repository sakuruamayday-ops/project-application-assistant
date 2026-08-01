from __future__ import annotations

import sqlite3

from app.knowledge_case_packs import case_pack_capability, query_case_packs


def case_pack_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE documents(
            id INTEGER PRIMARY KEY,title TEXT,source TEXT,document_role TEXT,
            validity_status TEXT,verification_status TEXT
        );
        CREATE TABLE case_packs(
            case_pack_id TEXT PRIMARY KEY,project_id TEXT,project_name TEXT,title TEXT,
            enterprise_name TEXT,year INTEGER,batch TEXT,industry TEXT,
            enterprise_scale TEXT,sensitivity TEXT,verification_status TEXT,
            source_root TEXT,document_count INTEGER,created_at TEXT
        );
        CREATE TABLE case_pack_documents(
            case_pack_id TEXT,document_id INTEGER UNIQUE,document_type TEXT,
            evidence_type TEXT,sequence INTEGER
        );
        CREATE TABLE document_relations(
            source_document_id INTEGER,target_document_id INTEGER,
            relation_type TEXT,evidence TEXT
        );
        INSERT INTO case_packs VALUES(
            'case-1','hangzhou-enterprise-technology-center','杭州市企业技术中心',
            '甲企业2024案例','甲企业',2024,'','制造业','中型','internal','confirmed',
            '技术中心/甲企业',2,'2026-08-01T00:00:00Z'
        );
        INSERT INTO documents VALUES(1,'申报书','/case/application.docx','60_申报案例与建设方案','active','confirmed');
        INSERT INTO documents VALUES(2,'财务附件','/case/finance.pdf','60_申报案例与建设方案','active','confirmed');
        INSERT INTO case_pack_documents VALUES('case-1',1,'application','',1);
        INSERT INTO case_pack_documents VALUES('case-1',2,'evidence_attachment','financial',2);
        """
    )
    return connection


def test_case_pack_capability_and_layered_query():
    connection = case_pack_database()
    assert case_pack_capability(connection) == {
        "knowledge_schema_version": "2.0",
        "case_pack_capability": True,
        "case_pack_count": 1,
    }
    result = query_case_packs(
        connection,
        project_id="hangzhou-enterprise-technology-center",
        section="financial",
    )
    assert result["status"] == "ok"
    assert result["result_count"] == 1
    assert [item["document_id"] for item in result["results"][0]["documents"]] == [2]
    assert "不得把案例企业事实复制" in result["results"][0]["reference_boundary"]


def test_old_index_reports_capability_unavailable_without_fallback():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE documents(id INTEGER PRIMARY KEY)")
    result = query_case_packs(connection, query="技术中心")
    assert result["status"] == "unavailable"
    assert result["results"] == []
    assert result["case_pack_capability"] is False
