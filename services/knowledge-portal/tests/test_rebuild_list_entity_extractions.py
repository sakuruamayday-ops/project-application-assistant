from __future__ import annotations

import sqlite3

import pytest

from scripts.rebuild_list_entity_extractions import rebuild


def create_database(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            canonical_project_name TEXT NOT NULL,
            policy_year INTEGER,
            batch TEXT NOT NULL,
            region TEXT NOT NULL,
            document_stage TEXT NOT NULL,
            document_role TEXT NOT NULL
        );
        CREATE TABLE enterprise_mentions (
            document_id INTEGER NOT NULL,
            enterprise_name TEXT NOT NULL,
            sequence_no TEXT NOT NULL,
            context TEXT NOT NULL,
            UNIQUE(document_id, enterprise_name, sequence_no, context)
        );
        CREATE TABLE public_list_entities (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
            enterprise_name TEXT NOT NULL,
            sequence_no TEXT NOT NULL,
            canonical_project_name TEXT NOT NULL,
            policy_year INTEGER,
            batch TEXT NOT NULL,
            region TEXT NOT NULL,
            list_status TEXT NOT NULL,
            context TEXT NOT NULL,
            confidence TEXT NOT NULL,
            UNIQUE(document_id, enterprise_name, sequence_no, canonical_project_name,
                   policy_year, batch, region, list_status, context, confidence)
        );
        INSERT INTO documents VALUES(
            1, '正文未保留结构化行', '国家专精特新“小巨人”企业', 2024, '第六批',
            '浙江省', '认定名单', '50_名单与对标'
        );
        INSERT INTO enterprise_mentions VALUES(1, '结构化企业有限公司', '1', '结构化源');
        INSERT INTO public_list_entities(
            document_id, enterprise_name, sequence_no, canonical_project_name,
            policy_year, batch, region, list_status, context, confidence
        ) VALUES(
            1, '结构化企业有限公司', '1', '国家专精特新“小巨人”企业',
            2024, '第六批', '浙江省', '认定名单', '结构化源', 'high'
        );
        """
    )
    connection.commit()
    connection.close()


def test_rebuild_rolls_back_when_structured_rows_would_be_lost(tmp_path):
    database = tmp_path / "knowledge.sqlite3"
    create_database(database)

    with pytest.raises(RuntimeError, match="refusing to shrink"):
        rebuild(database)

    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT enterprise_name FROM public_list_entities"
    ).fetchall() == [("结构化企业有限公司",)]
    assert connection.execute(
        "SELECT enterprise_name FROM enterprise_mentions"
    ).fetchall() == [("结构化企业有限公司",)]
    connection.close()


def test_rebuild_requires_explicit_permission_to_shrink(tmp_path):
    database = tmp_path / "knowledge.sqlite3"
    create_database(database)

    result = rebuild(database, allow_shrink=True)

    assert result["previous_public_list_entities"] == 1
    assert result["public_list_entities"] == 0
