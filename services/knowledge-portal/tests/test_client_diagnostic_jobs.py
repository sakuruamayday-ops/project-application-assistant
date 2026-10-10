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


def add(db, report_id, status='pending', files=None, created='2026-10-07T09:00:00+00:00', context=None):
    if context is None:
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


def test_review_keeps_later_errors_and_distinct_failure_sequences():
    db = database()
    for report_id, later_error in [(1, 'PDF_SOURCE_MISMATCH'), (2, 'TOOL_NOT_FOUND')]:
        add(db, report_id)
        diagnostic = json.loads(db.execute(
            'SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=?', (report_id,)
        ).fetchone()[0])
        context = json.loads(diagnostic['conversation_context'])
        context['events'].append({'type': 'tool/result', 'data': {
            'message': {'isError': True, 'content': [{'text': later_error}]}
        }})
        diagnostic['conversation_context'] = json.dumps(context)
        db.execute('UPDATE client_error_reports SET diagnostic_json=? WHERE feedback_id=?',
                   (json.dumps(diagnostic), report_id))
    db.commit()
    result = review_pending(db, datetime(2026, 10, 9, 10, tzinfo=timezone.utc))
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert result['groups'] == 2
    assert 'PDF_SOURCE_MISMATCH' in document
    assert 'TOOL_NOT_FOUND' in document
    assert '首条错误不代表最终失败原因' in document


def test_review_explains_client_stage_recovery_and_delivery_without_confirming_root():
    db = database()
    primary = {'event_seq': 4, 'tool': 'gongchuang_skill_operation', 'operation': 'evidence-ledger.create-docx',
               'stage': 'output-validation', 'code': 'GC-SKILL-OUTPUT-PROTOCOL', 'category': 'runtime',
               'status': 'unrecovered', 'observed_reason': '标准输出为空', 'cause_status': 'confirmed-root',
               'execution': {'exitCode': 0, 'stdout': {'bytes': 0, 'json': 'empty'}, 'secret': 'not-copied'}}
    add(db, 1, context={'failed_turn': 2, 'events': [], 'failure_analysis': {
        'turn': 2, 'turn_result': 'completed', 'delivery_result': 'draft', 'primary_failure': primary,
        'failures': [
            {'event_seq': 1, 'tool': 'write', 'stage': 'tool-execution', 'category': 'runtime', 'status': 'recovered',
             'recovery_event_seq': 3, 'observed_reason': 'FS_STALE_VERSION'}, primary,
            {'event_seq': 5, 'tool': 'gongchuang_artifact_probe', 'stage': 'tool-execution', 'category': 'runtime',
             'status': 'unrecovered', 'blocked_by_event_seq': 4, 'observed_reason': 'ENOENT'},
            {'event_seq': 6, 'tool': 'web_search', 'stage': 'tool-execution', 'category': 'waiting-user',
             'status': 'expected-block', 'observed_reason': '等待 A/B/C 选择'},
        ], 'omitted_failure_count': 0}})
    assert review_pending(db, datetime(2026, 10, 9, 10, tzinfo=timezone.utc))['reviewed'] == 1
    review = json.loads(db.execute('SELECT review_json FROM client_diagnostic_reviews').fetchone()[0])
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '主要待排查失败：事件 4' in document and '阶段 output-validation' in document
    assert '同操作已恢复' in document and '恢复于事件 3' in document
    assert '关联事件 4' in document and '等待用户选择' in document
    assert '轮次结束状态 completed；专业交付状态 draft' in document
    assert '待复现' in review['root_cause']
    assert review['failure_analysis']['primary_failure']['cause_status'] == 'observed-failure-only'
    assert 'secret' not in review['failure_analysis']['primary_failure']['execution']


def test_review_keeps_recovered_and_unrecovered_reports_in_separate_groups():
    db = database()
    for report_id, status in [(1, 'unrecovered'), (2, 'recovered')]:
        failure = {'event_seq': 1, 'tool': 'write', 'stage': 'tool-execution', 'category': 'runtime',
                   'status': status, 'observed_reason': 'FS_STALE_VERSION'}
        add(db, report_id, context={'events': [], 'failure_analysis': {'turn': 1, 'turn_result': 'completed',
            'delivery_result': 'unknown', 'primary_failure': failure if status == 'unrecovered' else None,
            'failures': [failure]}})
    assert review_pending(db, datetime(2026, 10, 9, 10, tzinfo=timezone.utc))['groups'] == 2


def test_review_preserves_not_started_output_for_sandbox_permission_failure():
    db = database()
    failure = {'event_seq': 1, 'tool': 'gongchuang_skill_operation', 'stage': 'sandbox-permission',
               'category': 'runtime', 'status': 'unrecovered', 'observed_reason': 'SetNamedSecurityInfoW failed (Win32 5)',
               'execution': {'stdout': {'bytes': 0, 'json': 'not-started'}}}
    add(db, 1, context={'failed_turn': 1, 'events': [], 'failure_analysis': {'turn': 1,
        'primary_failure': failure, 'failures': [failure]}})
    assert review_pending(db, datetime(2026, 10, 10, 10, tzinfo=timezone.utc))['reviewed'] == 1
    review = json.loads(db.execute('SELECT review_json FROM client_diagnostic_reviews').fetchone()[0])
    assert review['failure_analysis']['primary_failure']['execution']['stdout']['json'] == 'not-started'
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert 'sandbox-permission' in document and 'not-started' in document


def test_review_ignores_wrong_turn_and_malformed_client_analysis_without_losing_other_reports():
    db = database()
    add(db, 1, context={'failed_turn': 2, 'events': [], 'failure_analysis': {'turn': 1, 'failures': []}})
    failure = {'event_seq': 1, 'tool': 'write', 'stage': 'tool-execution', 'category': 'runtime', 'status': 'unrecovered',
               'observed_reason': 'error', 'execution': {'stdout': {'json': ['invalid-type']}}}
    add(db, 2, context={'events': [], 'failure_analysis': {'turn': 1, 'primary_failure': failure, 'failures': [failure]}})
    assert review_pending(db, datetime(2026, 10, 9, 10, tzinfo=timezone.utc))['reviewed'] == 2
    first = json.loads(db.execute('SELECT review_json FROM client_diagnostic_reviews WHERE report_id=1').fetchone()[0])
    assert 'failure_analysis' not in first
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '未提供结构化对话失败阶段' in document


def test_review_retains_independent_report_preparation_failure_without_session_events():
    db = database()
    add(db, 1, context={'events': [], 'failure_stage': 'report-preparation',
        'error': {'name': 'Error', 'message': 'session inspection unavailable'},
        'failure_analysis': {'turn': None, 'failures': [], 'primary_failure': None}})
    assert review_pending(db, datetime(2026, 10, 9, 10, tzinfo=timezone.utc))['reviewed'] == 1
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert 'report-preparation' in document and 'session inspection unavailable' in document


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
