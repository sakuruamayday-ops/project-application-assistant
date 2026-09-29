from __future__ import annotations

import sqlite3

from scripts.build_recognition_search_index import build_index
from scripts.recognition_text_index import rebuild_recognition_text_index
from app.recognized_enterprise_discovery import recognition_search


def database():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE documents(id INTEGER PRIMARY KEY,title TEXT,source TEXT);
        CREATE TABLE enterprise_mentions(id INTEGER PRIMARY KEY,document_id INTEGER,
            enterprise_name TEXT,context TEXT);
        INSERT INTO documents VALUES(1,'工业机器人测试资料','fixture');
        INSERT INTO enterprise_mentions VALUES(1,1,'共创测试企业甲','工业机器人控制器');
        INSERT INTO enterprise_mentions VALUES(2,1,'共创测试企业乙','卫生湿巾');
    ''')
    build_index(db)
    return db


def matches(db, term):
    return list(db.execute('''SELECT kind,source_id FROM recognition_text_rows WHERE id IN
        (SELECT rowid FROM recognition_text_fts WHERE recognition_text_fts MATCH ?)
        ORDER BY kind,source_id''', ('"'+term+'"',)))


def page(db, term, offset=0):
    return recognition_search(db, query=term+'有哪些小巨人', subject_terms=[term], result_group='pending', limit=1, offset=offset)


def test_index_scan_and_short_term_pages_agree():
    db = database()
    indexed = {(term, offset): page(db, term, offset) for term in ('工业机器人', '湿巾') for offset in (0, 1)}
    db.execute('ALTER TABLE recognition_text_fts RENAME TO hidden_text_fts')
    for (term, offset), expected in indexed.items():
        assert page(db, term, offset) == expected


def test_import_edits_deletes_and_rebuild_keep_text_index_current():
    db = database()
    assert matches(db, '工业机器人')
    db.execute("UPDATE documents SET title='智能水表' WHERE id=1")
    assert ('mention','2') in [tuple(row) for row in matches(db, '智能水表')]
    db.execute("UPDATE enterprise_mentions SET context='四足机器人' WHERE id=2")
    assert ('mention','2') in [tuple(row) for row in matches(db, '四足机器人')]
    db.execute("INSERT INTO enterprise_mentions VALUES(3,1,'共创测试企业丙','卫生湿巾')")
    assert ('mention','3') in [tuple(row) for row in matches(db, '卫生湿巾')]
    db.execute('DELETE FROM enterprise_mentions WHERE id=3')
    assert ('mention','3') not in [tuple(row) for row in matches(db, '卫生湿巾')]
    db.execute("UPDATE enterprise_subject_evidence SET raw_subject='测试新产品', evidence_excerpt='测试新产品' WHERE evidence_id=(SELECT evidence_id FROM enterprise_subject_evidence LIMIT 1)")
    assert matches(db, '测试新产品')
    expected = [tuple(r) for r in matches(db, '测试新产品')]
    db.commit()
    db.execute('VACUUM')
    assert [tuple(r) for r in matches(db, '测试新产品')] == expected
    rebuild_recognition_text_index(db)
    assert [tuple(r) for r in matches(db, '测试新产品')] == expected
    db.execute("DELETE FROM enterprise_subject_evidence WHERE raw_subject='测试新产品'")
    assert not matches(db, '测试新产品')
    db.execute('DELETE FROM documents WHERE id=1')
    assert not [r for r in matches(db, '智能水表') if r['kind']=='mention']


def test_replace_keeps_one_current_source_record():
    db = database()
    db.execute("INSERT OR REPLACE INTO enterprise_mentions VALUES(1,1,'共创测试企业甲','新型传感器')")
    assert ('mention','1') in [tuple(r) for r in matches(db, '新型传感器')]
    assert db.execute("SELECT count(*) FROM recognition_text_rows WHERE kind='mention' AND source_id='1'").fetchone()[0] == 1
    build_index(db)
    assert ('mention','1') in [tuple(r) for r in matches(db, '新型传感器')]


def test_source_transaction_rollback_also_rolls_back_search_terms():
    db = database()
    before = [tuple(row) for row in matches(db, '工业机器人')]
    db.execute("UPDATE enterprise_mentions SET context='可回滚测试词' WHERE id=1")
    assert matches(db, '可回滚测试词')
    db.rollback()
    assert not matches(db, '可回滚测试词')
    assert [tuple(row) for row in matches(db, '工业机器人')] == before
