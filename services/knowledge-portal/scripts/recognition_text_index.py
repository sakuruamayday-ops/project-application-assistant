"""SQLite substring index for recognition evidence; source rows remain authoritative."""
from __future__ import annotations

import sqlite3


_TABLE = 'recognition_text_rows'
_FTS = 'recognition_text_fts'


def rebuild_recognition_text_index(connection: sqlite3.Connection) -> None:
    """Rebuild the derived index and keep existing import/edit paths synchronized."""
    for name in ('rows_ai', 'rows_ad', 'rows_au', 'subject_ai', 'subject_ad', 'subject_au',
                 'mention_ai', 'mention_ad', 'mention_au', 'document_au', 'document_ad'):
        connection.execute(f'DROP TRIGGER IF EXISTS recognition_text_{name}')
    connection.execute(f'DROP TABLE IF EXISTS {_FTS}')
    connection.execute(f'DROP TABLE IF EXISTS {_TABLE}')
    connection.execute(f'''CREATE TABLE {_TABLE}(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
        topic TEXT NOT NULL, title TEXT NOT NULL, context TEXT NOT NULL,
        UNIQUE(kind,source_id))''')
    connection.execute(f'''CREATE VIRTUAL TABLE {_FTS} USING fts5(
        topic,title,context,content='{_TABLE}',content_rowid='id',tokenize='trigram')''')
    connection.execute(f'''INSERT INTO {_TABLE}(kind,source_id,topic,title,context)
        SELECT 'subject',evidence_id,CASE WHEN match_level='exact' THEN canonical_subject ELSE '' END,
               raw_subject,evidence_excerpt FROM enterprise_subject_evidence''')
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    mentions = {'enterprise_mentions', 'documents'} <= tables
    if mentions:
        connection.execute(f'''INSERT INTO {_TABLE}(kind,source_id,topic,title,context)
            SELECT 'mention',CAST(em.id AS TEXT),'',COALESCE(d.title,''),COALESCE(em.context,'')
            FROM enterprise_mentions em JOIN documents d ON d.id=em.document_id''')
    connection.execute(f"INSERT INTO {_FTS}({_FTS}) VALUES('rebuild')")
    statements = [
        f'''CREATE TRIGGER recognition_text_rows_ai AFTER INSERT ON {_TABLE} BEGIN
            INSERT INTO {_FTS}(rowid,topic,title,context) VALUES(new.id,new.topic,new.title,new.context); END''',
        f'''CREATE TRIGGER recognition_text_rows_ad AFTER DELETE ON {_TABLE} BEGIN
            INSERT INTO {_FTS}({_FTS},rowid,topic,title,context)
            VALUES('delete',old.id,old.topic,old.title,old.context); END''',
        f'''CREATE TRIGGER recognition_text_rows_au AFTER UPDATE ON {_TABLE} BEGIN
            INSERT INTO {_FTS}({_FTS},rowid,topic,title,context)
            VALUES('delete',old.id,old.topic,old.title,old.context);
            INSERT INTO {_FTS}(rowid,topic,title,context) VALUES(new.id,new.topic,new.title,new.context); END''',
    ]
    subject_insert = f'''INSERT INTO {_TABLE}(kind,source_id,topic,title,context)
        VALUES('subject',new.evidence_id,CASE WHEN new.match_level='exact' THEN new.canonical_subject ELSE '' END,
               new.raw_subject,new.evidence_excerpt)
        ON CONFLICT(kind,source_id) DO UPDATE SET topic=excluded.topic,title=excluded.title,context=excluded.context;'''
    statements += [
        f'CREATE TRIGGER recognition_text_subject_ai AFTER INSERT ON enterprise_subject_evidence BEGIN {subject_insert} END',
        f'''CREATE TRIGGER recognition_text_subject_ad AFTER DELETE ON enterprise_subject_evidence BEGIN
            DELETE FROM {_TABLE} WHERE kind='subject' AND source_id=old.evidence_id; END''',
        f'''CREATE TRIGGER recognition_text_subject_au AFTER UPDATE ON enterprise_subject_evidence BEGIN
            DELETE FROM {_TABLE} WHERE kind='subject' AND source_id=old.evidence_id; {subject_insert} END''',
    ]
    if mentions:
        mention_insert = f'''INSERT INTO {_TABLE}(kind,source_id,topic,title,context)
            SELECT 'mention',CAST(new.id AS TEXT),'',COALESCE(d.title,''),COALESCE(new.context,'')
            FROM documents d WHERE d.id=new.document_id
            ON CONFLICT(kind,source_id) DO UPDATE SET title=excluded.title,context=excluded.context;'''
        statements += [
            f'CREATE TRIGGER recognition_text_mention_ai AFTER INSERT ON enterprise_mentions BEGIN {mention_insert} END',
            f'''CREATE TRIGGER recognition_text_mention_ad AFTER DELETE ON enterprise_mentions BEGIN
                DELETE FROM {_TABLE} WHERE kind='mention' AND source_id=CAST(old.id AS TEXT); END''',
            f'''CREATE TRIGGER recognition_text_mention_au AFTER UPDATE ON enterprise_mentions BEGIN
                DELETE FROM {_TABLE} WHERE kind='mention' AND source_id=CAST(old.id AS TEXT); {mention_insert} END''',
            f'''CREATE TRIGGER recognition_text_document_au AFTER UPDATE OF title,id ON documents BEGIN
                UPDATE {_TABLE} SET title=COALESCE(new.title,'') WHERE kind='mention' AND source_id IN
                (SELECT CAST(id AS TEXT) FROM enterprise_mentions WHERE document_id=new.id); END''',
            f'''CREATE TRIGGER recognition_text_document_ad BEFORE DELETE ON documents BEGIN
                DELETE FROM {_TABLE} WHERE kind='mention' AND source_id IN
                (SELECT CAST(id AS TEXT) FROM enterprise_mentions WHERE document_id=old.id); END''',
        ]
    for statement in statements:
        connection.execute(statement)
