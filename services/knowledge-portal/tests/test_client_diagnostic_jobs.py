import base64
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.client_diagnostic_jobs import DiagnosticChunk, initialize, receive_chunk, review_pending, purge_reviewed, file_path, _errors


def test_review_extracts_failed_tool_text_not_successful_content():
    assert _errors({'events': [
        {'type': 'tool/result', 'data': {'message': {'isError': False, 'content': [{'text': 'business text'}]}}},
        {'type': 'tool/result', 'data': {'message': {'isError': True, 'content': [{'text': 'MissingSessionID'}]}}},
        {'type': 'turn/end', 'data': {'reason': {'kind': 'error', 'reason': 'connection lost'}}},
    ]}) == ['MissingSessionID', 'connection lost']


def database():
    db = sqlite3.connect(':memory:')
    db.executescript('''
    CREATE TABLE feedback_messages(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
    CREATE TABLE client_error_reports(feedback_id INTEGER PRIMARY KEY,diagnostic_json TEXT);
    ''')
    initialize(db)
    return db


def test_review_uses_failed_turn_not_errors_in_earlier_context():
    assert _errors({'failed_turn': 2, 'events': [
        {'type': 'turn/end', 'data': {'turn': 1, 'reason': {'kind': 'error', 'message': 'old missing key'}}},
        {'type': 'tool/result', 'data': {'turn': 2, 'message': {'isError': True, 'content': [{'text': 'current parse error'}]}}},
    ]}) == ['current parse error']


def add(db, report_id, status='pending', files=None, created='2026-10-07T09:00:00+00:00'):
    context = {'events': [{'type': 'tool/result', 'data': {'message': {'isError': True}, 'error': 'DOCX_PARSE_FAILED'}}], 'diagnostic_files': files or []}
    db.execute('INSERT INTO feedback_messages VALUES (?,?,?)', (report_id, status, created))
    db.execute('INSERT INTO client_error_reports VALUES (?,?)', (report_id, json.dumps({'code': 'GC-AUTO-FAILURE', 'client_version': '0.6.1', 'conversation_context': json.dumps(context)})))
    db.commit()


def chunk(file_id, offset=0, data=b'ab', size=4):
    return DiagnosticChunk(file_id=file_id, name='test.docx', size=size, offset=offset, data=base64.b64encode(data).decode())


def test_resumes_and_retransmits_without_duplicate_bytes(tmp_path):
    db = database()
    add(db, 1)
    fid = str(uuid4())
    assert receive_chunk(db, tmp_path, 1, chunk(fid))['next_offset'] == 2
    assert receive_chunk(db, tmp_path, 1, chunk(fid))['next_offset'] == 2
    assert receive_chunk(db, tmp_path, 1, chunk(fid, 2, b'cd')) == {'next_offset': 4, 'complete': True}
    assert file_path(tmp_path, 1, fid).read_bytes() == b'abcd'
    with pytest.raises(ValueError):
        receive_chunk(db, tmp_path, 1, chunk(fid, 4, b'x'))


def test_review_waits_for_files_and_never_asserts_root_cause(tmp_path):
    db = database()
    fid = str(uuid4())
    add(db, 1, files=[{'file_id': fid, 'status': 'pending'}], created='2026-10-08T09:00:00+00:00')
    now = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
    assert review_pending(db, now)['reviewed'] == 0
    receive_chunk(db, tmp_path, 1, chunk(fid, data=b'abcd'))
    assert review_pending(db, now)['reviewed'] == 1
    assert review_pending(db, now)['reviewed'] == 1
    doc = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert 'DOCX_PARSE_FAILED' in doc and '待复现' in doc


def test_expiry_keeps_today_unresolved_and_unreviewed(tmp_path):
    db = database()
    add(db, 1, 'resolved')
    add(db, 2, 'pending')
    add(db, 3, 'closed', created='2026-10-07T16:00:00+00:00')  # Oct 8 in Shanghai.
    review_pending(db, datetime(2026, 10, 8, 10, tzinfo=timezone.utc))
    add(db, 4, 'resolved')
    result = purge_reviewed(db, tmp_path, datetime(2026, 10, 8, 15, tzinfo=timezone.utc))
    assert result['purged_report_ids'] == [1]
    assert purge_reviewed(db, tmp_path, datetime(2026, 10, 8, 15, tzinfo=timezone.utc))['purged_report_ids'] == []
    assert json.loads(db.execute('SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=2').fetchone()[0])['code'] == 'GC-AUTO-FAILURE'


def test_expiry_removes_only_resolved_diagnostic_copy(tmp_path):
    db = database()
    add(db, 1, 'resolved')
    fid = str(uuid4())
    receive_chunk(db, tmp_path, 1, chunk(fid, data=b'abcd'))
    unrelated = tmp_path / 'business.docx'
    unrelated.write_bytes(b'keep')
    review_pending(db, datetime(2026, 10, 8, 10, tzinfo=timezone.utc))
    result = purge_reviewed(db, tmp_path, datetime(2026, 10, 8, 15, tzinfo=timezone.utc))
    assert result['reclaimed_bytes'] == 4
    assert unrelated.read_bytes() == b'keep'
    assert not file_path(tmp_path, 1, fid).exists()
    with pytest.raises(ValueError, match='expired'):
        receive_chunk(db, tmp_path, 1, chunk(fid, data=b'abcd'))


def test_incomplete_old_report_does_not_block_other_expiry(tmp_path):
    db = database()
    fid = str(uuid4())
    add(db, 1, 'resolved', files=[{'file_id': fid, 'status': 'pending'}])
    receive_chunk(db, tmp_path, 1, chunk(fid))
    add(db, 2, 'resolved')
    review_pending(db, datetime(2026, 10, 8, 10, tzinfo=timezone.utc))
    result = purge_reviewed(db, tmp_path, datetime(2026, 10, 8, 15, tzinfo=timezone.utc))
    assert result['purged_report_ids'] == [2]
    assert file_path(tmp_path, 1, fid).read_bytes() == b'ab'
