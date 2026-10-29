import base64
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.client_diagnostic_jobs import DiagnosticChunk, initialize, receive_chunk, review_pending, purge_reviewed, file_path, _errors, _turn_outcome, _failure_analysis, _analysis_lines, _outcome_lines


def test_review_preserves_file_protection_without_treating_it_as_a_runtime_failure():
    protection = {'event_seq': 2, 'tool': 'gongchuang_skill_operation', 'stage': 'tool-execution',
                  'category': 'protection', 'status': 'expected-block', 'observed_reason': 'FileExistsError: synthetic output'}
    analysis = _failure_analysis({'failed_turn': 1, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'completed', 'delivery_result': 'unknown', 'failures': [protection],
        'first_failure': protection, 'primary_failure': None,
    }})
    assert analysis['failures'][0]['category'] == 'protection'
    assert analysis['failures'][0]['status'] == 'expected-block'
    assert analysis['primary_failure'] is None
    rendered = '\n'.join(_analysis_lines(analysis))
    assert '文件保护提示' in rendered
    assert 'FileExistsError: synthetic output' in rendered


def test_review_extracts_failed_tool_text_not_successful_content():
    assert _errors({'events': [
        {'type': 'tool/result', 'data': {'message': {'isError': False, 'content': [{'text': 'business text'}]}}},
        {'type': 'tool/result', 'data': {'message': {'isError': True, 'content': [{'text': 'MissingSessionID'}]}}},
        {'type': 'turn/end', 'data': {'reason': {'kind': 'error', 'reason': 'connection lost'}}},
    ]}) == ['MissingSessionID', 'connection lost']


@pytest.mark.parametrize('operation', ['workspace', 'conversation'])
def test_review_records_failed_host_deletion_without_conversation_events(operation):
    context = {'events': [], 'module': 'enterprise-trash', 'failure_stage': operation + '-deletion',
               'user_operation': {'operation': operation, 'result': 'failed', 'target_id': 'synthetic-id'},
               'error': {'name': 'Error', 'message': 'synthetic cold record missing'}}
    assert 'synthetic cold record missing' in _errors(context)
    outcome = _turn_outcome(context, None)
    assert outcome['status'] == 'not-delivered'
    assert outcome['verification_scope'] == 'host-operation-only'
    db = database()
    add(db, 1, context=context)
    assert review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))['reviewed'] == 1
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '目标操作未完成' in document
    assert 'synthetic cold record missing' in document
    assert '目标文件未交付' not in document
    assert '待复现' in document


def test_review_does_not_infer_host_deletion_from_unowned_operation_fields():
    context = {'events': [], 'user_operation': {'operation': 'conversation', 'result': 'failed'},
               'failure_stage': 'conversation-deletion'}
    assert _turn_outcome(context, None)['verification_scope'] == 'file-delivery-only'
    assert _turn_outcome(context, None)['status'] == 'unknown'


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


def outcome_event(kind, seq, **data):
    return {'type': kind, 'seq': seq, 'data': {'turn': 1, **data}}


@pytest.mark.parametrize('scenario,status', [
    ('text', 'answered'), ('requested-file', 'not-delivered'),
    ('progress', 'unknown'), ('cancelled', 'cancelled'),
])
def test_review_separates_final_text_from_file_delivery_and_json_structure(scenario, status):
    failure = dict(event_seq=2, tool='web_fetch', stage='tool-execution', category='runtime',
        status='unrecovered', observed_reason='WEB_REDIRECT_BLOCKED')
    reply_content = [{'type': 'text', 'text': '已有资料的解释如下。'}]
    if scenario == 'progress':
        reply_content.append({'type': 'tool-call', 'name': 'web_fetch'})
    context = {'failed_turn': 1, 'events': [
        outcome_event('user/message', 1, source={'kind': 'user'}, content=[{'type': 'text',
            'text': '生成PDF文件' if scenario == 'requested-file' else '阅读资料并解释要求。'}]),
        outcome_event('assistant/message', 3, message={'content': reply_content}),
        outcome_event('turn/end', 4, reason={'kind': 'aborted' if scenario == 'cancelled' else 'completed'}),
    ], 'failure_analysis': {'turn': 1, 'turn_result': 'completed', 'failures': [failure], 'primary_failure': failure}}
    analysis = _failure_analysis(context)
    outcome = _turn_outcome(context, analysis)
    assert outcome['status'] == status
    assert outcome['files'] == []
    assert analysis['failures'][0]['status'] == 'unrecovered'
    if scenario == 'text':
        assert outcome['verification_scope'] == 'text-response-only'
        lines = '\n'.join(_outcome_lines(outcome))
        assert '已记录最终文字回复' in lines
        assert 'JSON 对象结构' not in lines
        assert '文件回执只证明交付' not in lines


def test_review_retains_only_numeric_ocr_page_recovery_observations():
    failure = dict(event_seq=2, tool='mcp__paddle_ocr__workspace_pdf', stage='service-timeout', category='runtime',
        status='unrecovered', observed_reason='Request timed out',
        page_recovery={'requested_pages': [1, 2, 3, 4], 'covered_pages': [1, 2], 'document': 'do-not-copy-path'})
    context = {'failed_turn': 1, 'failure_analysis': {'turn': 1, 'turn_result': 'completed', 'failures': [failure]}}
    analysis = _failure_analysis(context)
    assert analysis['failures'][0]['page_recovery'] == {'requested_pages': [1, 2, 3, 4], 'covered_pages': [1, 2]}
    assert 'OCR后续成功页覆盖 2/4 页' in '\n'.join(_analysis_lines(analysis))
    assert 'do-not-copy-path' not in json.dumps(analysis)
    failure['page_recovery']['covered_pages'] = [9]
    assert 'page_recovery' not in _failure_analysis(context)['failures'][0]


@pytest.mark.parametrize('transport', ['native', 'ptc'])
def test_review_uses_the_actual_pdf_delivery_receipt_path(transport):
    arguments = {'sourceArtifactPath': '/enterprise/source.html', 'outputPath': '/enterprise/requested.pdf'}
    meta = {'paths': ['/enterprise/current/final.pdf']}
    context = {'failed_turn': 1, 'events': [
        outcome_event('user/message', 1, source={'kind': 'user'}, content=[{'type': 'text', 'text': '给我生成PDF文件'}]),
    ]}
    if transport == 'native':
        context['events'].extend([
            outcome_event('tool/call', 2, callId='pdf', name='gongchuang_deliver_pdf', arguments=json.dumps(arguments)),
            outcome_event('tool/result', 3, meta=meta, message={'toolCallId': 'pdf', 'isError': False}),
        ])
    else:
        context['events'].append(outcome_event('tool/ptc-dispatch', 3, name='gongchuang_deliver_pdf',
            arguments=arguments, isError=False, meta=meta))
    context['events'].append(outcome_event('turn/end', 4, reason={'kind': 'completed'}))
    outcome = _turn_outcome(context, None)
    assert outcome['status'] == 'delivered'
    assert outcome['verification_scope'] == 'file-delivery-only'
    assert outcome['files'] == [{'name': 'final.pdf', 'format': 'pdf', 'phase': 'published', 'event_seq': 3, 'source': 'gongchuang_deliver_pdf'}]


@pytest.mark.parametrize('meta,is_error', [({}, False), ({'paths': []}, False),
    ({'paths': ['guess.pdf']}, False), ({'paths': ['/one.pdf', '/two.pdf']}, False),
    ({'paths': ['/one.pdf']}, True), ({'paths': ['/one.pdf']}, None)])
def test_review_does_not_invent_pdf_delivery_from_input_paths_or_invalid_receipts(meta, is_error):
    context = {'failed_turn': 1, 'events': [
        outcome_event('user/message', 1, source={'kind': 'user'}, content=[{'type': 'text', 'text': '生成PDF文件'}]),
        outcome_event('tool/ptc-dispatch', 2, name='gongchuang_deliver_pdf', arguments={'outputPath': '/request.pdf'},
            isError=is_error, meta=meta, content=[{'type': 'text', 'text': '已完成PDF'}]),
        outcome_event('turn/end', 3, reason={'kind': 'completed'}),
    ]}
    assert _turn_outcome(context, None)['status'] == 'not-delivered'
    assert _turn_outcome(context, None)['files'] == []


def test_review_keeps_cropped_pdf_receipts_without_promoting_them_to_business_final():
    context = {'failed_turn': 1, 'omitted_event_count': 4, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'completed', 'failures': [], 'outcome': {
            'goal_request': {'event_seq': 1, 'text': '生成PDF文件'}, 'requested_formats': ['pdf'], 'file_requested': True,
            'files': [{'name': 'report.pdf', 'format': 'pdf', 'phase': 'published', 'event_seq': 3, 'source': 'gongchuang_deliver_pdf'}],
            'unpublished_files': [],
        }}}
    outcome = _turn_outcome(context, _failure_analysis(context))
    assert outcome['status'] == 'delivered'
    assert outcome['files'][0]['phase'] == 'published'


def test_review_checks_final_requested_pdf_not_a_model_completion_claim_or_attachment():
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '给我转成PDF格式'}]}},
        outcome_event('assistant/message', 2, message={'content': [
            {'type': 'reasoning', 'text': 'must-not-copy'}, {'type': 'text', 'text': 'PDF 已完成'}]}),
        outcome_event('turn/end', 3, reason={'kind': 'completed'}),
    ], 'diagnostic_files': [{'name': 'input.pdf', 'status': 'pending'}]}
    result = _turn_outcome(context, None)
    assert result['status'] == 'not-delivered'
    assert result['files'] == []
    assert result['last_reply']['text'] == 'PDF 已完成'
    assert 'must-not-copy' not in json.dumps(result)
    context['events'].insert(2, outcome_event('tool/ptc-dispatch', 4, name='gongchuang_artifact_probe',
        arguments={'artifactPath': 'report.html'}, isError=False))
    assert _turn_outcome(context, None)['status'] == 'not-delivered'


def test_review_retains_a_published_word_when_later_pdf_work_is_interrupted():
    context = {'failed_turn': 1, 'events': [
        outcome_event('tool/ptc-dispatch', 518, name='gongchuang_artifact_probe', arguments={'artifactPath': 'C:\\空间\\回填.docx'}, isError=False),
        outcome_event('tool/ptc-dispatch', 520, name='gongchuang_publish_files', arguments={'paths': ['C:\\空间\\回填.docx']}, isError=False),
        outcome_event('tool/ptc-dispatch', 539, name='gongchuang_render_pdf', arguments={'outputPath': 'report.pdf'}, isError=True),
        outcome_event('turn/end', 541, reason={'kind': 'interrupted'}),
    ]}
    result = _turn_outcome(context, None)
    assert result['status'] == 'partial'
    assert result['files'] == [{'name': '回填.docx', 'format': 'docx', 'phase': 'published', 'event_seq': 520, 'source': 'gongchuang_publish_files'}]
    assert result['unpublished_files'][0]['name'] == 'report.pdf'
    assert 'C:' not in json.dumps(result)


def test_review_preserves_final_outcome_computed_before_cropping_but_not_unsupported_success():
    outcome = {'status': 'delivered', 'requested_formats': ['pdf'],
        'user_request': {'event_seq': 1, 'text': '输出PDF', 'truncated': False},
        'last_reply': {'event_seq': 8, 'text': '已交付', 'truncated': False, 'final': True},
        'files': [{'name': 'report.pdf', 'format': 'pdf', 'phase': 'formal', 'event_seq': 7, 'source': 'professional-notice'}],
        'unpublished_files': []}
    context = {'failed_turn': 1, 'omitted_event_count': 2, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'completed', 'delivery_result': 'formal', 'failures': [], 'outcome': outcome}}
    result = _turn_outcome(context, _failure_analysis(context))
    assert result['status'] == 'delivered' and result['last_reply']['final']
    outcome['files'] = []
    result = _turn_outcome(context, _failure_analysis(context))
    assert result['status'] != 'delivered'


@pytest.mark.parametrize('code,message,stage', [
    ('QUOTA', 'Insufficient Balance', 'model-balance'),
    ('QUOTA', 'rate limit exceeded', 'model-quota'),
    ('GC-ACCOUNT-UPGRADE', '最低支持版本为 V0.6.4', 'client-upgrade'),
    ('MISSING_CREDENTIAL', 'no API key', 'model-credentials'),
])
def test_review_separates_account_conditions_from_execution_faults(code, message, stage):
    failure = dict(event_seq=3, tool='turn', stage='turn-execution', code=code, category='runtime', status='unrecovered', observed_reason=message)
    context = {'failed_turn': 1, 'events': [outcome_event('turn/end', 3, reason={'kind': 'error', 'error': {'code': code, 'message': message}})],
        'failure_analysis': {'turn': 1, 'turn_result': 'error', 'delivery_result': 'unknown', 'failures': [failure], 'primary_failure': failure}}
    analysis = _failure_analysis(context)
    assert analysis['primary_failure']['stage'] == stage
    assert _turn_outcome(context, analysis)['status'] == 'blocked'
    db = database()
    add(db, 1, context=context)
    review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
    doc = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '账号条件或用户确认阻塞' in doc
    assert '不等同于文件生成程序故障' in doc


def test_review_handles_old_upgrade_clients_and_preserves_failure_details_after_outcome():
    context = {'failed_turn': 1, 'events': [outcome_event('turn/end', 17,
        reason={'kind': 'error', 'error': {'code': 'GC-ACCOUNT-UPGRADE', 'message': '最低支持版本为 V0.6.4'}})]}
    assert _turn_outcome(context, None)['status'] == 'blocked'
    db = database()
    add(db, 1, context=context)
    review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
    doc = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert doc.index('最终结果：') < doc.index('GC-ACCOUNT-UPGRADE')
    assert '不等同于文件生成程序故障' in doc


def test_review_keeps_recovered_delivery_and_missing_delivery_in_separate_groups():
    db = database()
    for report_id, path in [(1, 'report.pdf'), (2, None)]:
        events = [{'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '输出PDF'}]}}]
        if path:
            events.append(outcome_event('tool/ptc-dispatch', 2, name='gongchuang_artifact_probe', arguments={'artifactPath': path}, isError=False))
        events.append(outcome_event('turn/end', 3, reason={'kind': 'completed'}))
        add(db, report_id, context={'failed_turn': 1, 'events': events})
    assert review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))['groups'] == 2
    results = [json.loads(row[0])['outcome']['status'] for row in db.execute('SELECT review_json FROM client_diagnostic_reviews ORDER BY report_id')]
    assert results == ['delivered', 'not-delivered']


def test_review_does_not_turn_a_recovered_account_condition_back_into_an_active_block():
    failure = dict(event_seq=2, tool='model-connection', stage='tool-execution', code='QUOTA', category='runtime',
        status='recovered', recovery_event_seq=3, observed_reason='Insufficient Balance')
    context = {'failed_turn': 1, 'events': [
        outcome_event('tool/ptc-dispatch', 4, name='gongchuang_artifact_probe', arguments={'artifactPath': 'report.pdf'}, isError=False),
        outcome_event('turn/end', 5, reason={'kind': 'completed'}),
    ], 'failure_analysis': {'turn': 1, 'turn_result': 'completed', 'failures': [failure], 'primary_failure': None}}
    analysis = _failure_analysis(context)
    assert analysis['failures'][0]['status'] == 'recovered'
    assert analysis['failures'][0]['stage'] == 'model-balance'
    assert _turn_outcome(context, analysis)['status'] == 'delivered'


@pytest.mark.parametrize('request_text,publish,status,formats', [
    ('不要生成PDF，给我Word版本', True, 'delivered', ['docx']),
    ('能生成PDF文件吗？', False, 'unknown', []),
])
def test_review_does_not_require_negated_formats_or_capability_question_files(request_text, publish, status, formats):
    events = [{'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': request_text}]}}]
    if publish:
        events.append(outcome_event('tool/ptc-dispatch', 2, name='gongchuang_artifact_probe', arguments={'artifactPath': 'application.docx'}, isError=False))
    events.append(outcome_event('turn/end', 3, reason={'kind': 'completed'}))
    outcome = _turn_outcome({'failed_turn': 1, 'events': events}, None)
    assert outcome['status'] == status
    assert outcome['requested_formats'] == formats


def test_review_ignores_malformed_opaque_context_ids_without_losing_other_reports():
    db = database()
    add(db, 1, context={'failed_turn': 1, 'events': [
        outcome_event('tool/call', 1, callId=[], name='gongchuang_artifact_probe'),
        outcome_event('tool/result', 2, message={'toolCallId': {}, 'isError': False}),
        outcome_event('turn/end', 3, reason={'kind': 'error', 'error': {'code': []}}),
    ], 'failure_analysis': {'turn': 1, 'turn_result': 'error', 'failures': [],
        'outcome': {'files': [{'name': 'report.pdf', 'event_seq': 2, 'source': []}]}}})
    add(db, 2)
    assert review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))['reviewed'] == 2
    review = json.loads(db.execute('SELECT review_json FROM client_diagnostic_reviews WHERE report_id=1').fetchone()[0])
    assert review['outcome']['files'] == []


def test_review_keeps_occurrence_and_late_receipt_dates_distinct():
    db = database()
    add(db, 1, created='2026-10-12T00:59:57+00:00')
    raw = json.loads(db.execute('SELECT diagnostic_json FROM client_error_reports').fetchone()[0])
    raw['occurred_at'] = '2026-10-11T09:25:25Z'
    db.execute('UPDATE client_error_reports SET diagnostic_json=?', (json.dumps(raw),))
    db.commit()
    review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
    review = json.loads(db.execute('SELECT review_json FROM client_diagnostic_reviews').fetchone()[0])
    assert review['occurred_at'] == '2026-10-11T09:25:25Z'
    doc = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '2026-10-11T09:25:25Z' in doc and '2026-10-12T00:59:57+00:00' in doc


@pytest.mark.parametrize('reply_text,status,structure', [
    ('{"products":[]}', 'answered', 'valid-object'),
    ('下面是JSON。\n{"products":[]}', 'not-delivered', 'invalid'),
    ('```json\n{"products":[]}\n```', 'not-delivered', 'invalid'),
    ('[]', 'not-delivered', 'invalid'),
    ('{"products":', 'not-delivered', 'invalid'),
    ('', 'not-delivered', 'absent'),
])
def test_review_checks_json_only_goal_before_a_continue_request(reply_text, status, structure):
    goal = '根据给定字段整理测算方案，只输出一个 JSON 对象，不调用工具，不写文件。'
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': goal}]}},
        {'type': 'user/message', 'seq': 2, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '继续'}]}},
        outcome_event('assistant/message', 3, message={'content': [{'type': 'text', 'text': reply_text}]}),
        outcome_event('turn/end', 4, reason={'kind': 'blocked'}),
    ]}
    outcome = _turn_outcome(context, None)
    assert outcome['status'] == status and outcome['structured_reply'] == structure
    assert outcome['verification_scope'] == 'json-structure-only'
    assert outcome['goal_request']['text'] == goal
    assert outcome['user_request']['text'] == '继续'
    db = database()
    add(db, 1, context=context)
    review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '仅检查 JSON 结构' in document and goal in document
    assert ('JSON-only 要求未满足' in document) == (structure != 'valid-object')


def test_review_preserves_complete_json_structure_observation_after_event_crop():
    context = {'failed_turn': 1, 'events': [], 'omitted_event_count': 5, 'failure_analysis': {
        'turn': 1, 'turn_result': 'completed', 'failures': [], 'outcome': {
            'goal_request': {'event_seq': 1, 'text': '只返回JSON对象'},
            'last_reply': {'event_seq': 9, 'text': '{"text":"' + 'x' * 2990, 'truncated': True, 'final': True},
            'structured_reply': 'valid-object',
        }}}
    outcome = _turn_outcome(context, _failure_analysis(context))
    assert outcome['status'] == 'answered' and outcome['last_reply']['truncated']
    context['failure_analysis']['outcome']['structured_reply'] = []
    assert _turn_outcome(context, _failure_analysis(context))['status'] != 'answered'


def test_review_does_not_call_unresolved_recognition_failure_a_normal_confirmation_stop():
    failure = dict(event_seq=1, tool='recognition_search', stage='tool-execution', category='runtime',
        status='unrecovered', observed_reason='暂不支持的认定项目：创新型中小企业')
    context = {'failed_turn': 1, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'blocked', 'delivery_result': 'draft', 'failures': [failure], 'primary_failure': failure}}
    assert _turn_outcome(context, _failure_analysis(context))['status'] == 'not-delivered'


def test_review_records_refused_json_only_model_request_as_undelivered():
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '只输出一个JSON对象'}]}},
        outcome_event('turn/end', 2, reason={'kind': 'error', 'error': {'code': 'INVALID_REQUEST', 'message': 'unsupported developer role'}}),
    ]}
    assert _turn_outcome(context, None)['status'] == 'not-delivered'


def test_review_does_not_accept_a_missing_tool_success_flag_or_ignore_failed_host_delivery():
    publication = outcome_event('tool/ptc-dispatch', 1, name='gongchuang_artifact_probe', arguments={'artifactPath': 'report.pdf'})
    context = {'failed_turn': 1, 'events': [publication, outcome_event('turn/end', 3, reason={'kind': 'completed'})]}
    assert _turn_outcome(context, None)['files'] == []
    publication['data']['isError'] = False
    context['events'].insert(1, {'type': 'user/message', 'seq': 2, 'data': {'source': {
        'kind': 'plugin:gongchuang-policy-gate', 'delivery': {'turn': 1, 'phase': 'failed', 'files': []}}}})
    assert _turn_outcome(context, None)['status'] == 'partial'


def test_review_retains_actual_request_model_without_keys_before_event_crop():
    observed = dict(event_seq=8, provider='commandcode', model='Qwen/Qwen3.8-Max', apiKey='must-not-copy')
    context = {'failed_turn': 1, 'omitted_event_count': 2, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'error', 'failures': [], 'model_request': observed}}
    analysis = _failure_analysis(context)
    assert analysis['model_request'] == {key: observed[key] for key in ('event_seq', 'provider', 'model')}
    assert 'must-not-copy' not in json.dumps(analysis)
    context['failure_analysis'].pop('model_request')
    context['events'] = [outcome_event('request/header', 8, header={'config': observed})]
    assert _failure_analysis(context)['model_request']['model'] == 'Qwen/Qwen3.8-Max'
    db = database()
    add(db, 1, context=context)
    review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))
    document = db.execute('SELECT document FROM client_diagnostic_days').fetchone()[0]
    assert '本轮最后一次实际模型请求：commandcode / Qwen/Qwen3.8-Max' in document


def test_review_keeps_identical_failures_on_different_actual_models_separate():
    db = database()
    for report_id, model in enumerate(['Qwen/Qwen3.8-Max', 'Qwen/Qwen3.8-Flash'], 1):
        add(db, report_id, context={'failed_turn': 1, 'events': [], 'failure_analysis': {
            'turn': 1, 'turn_result': 'error', 'failures': [],
            'model_request': {'event_seq': 8, 'provider': 'commandcode', 'model': model}}})
    assert review_pending(db, datetime(2026, 10, 12, 10, tzinfo=timezone.utc))['groups'] == 2


def test_review_records_report_goal_without_file_although_draft_stop_has_no_runtime_error():
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': '杭州焙焙家食品有限公司 给我一份企业全景报告'}]}},
        outcome_event('user/message', 2, source={'kind': 'plugin:gongchuang-policy-gate', 'delivery': {'turn': 1, 'phase': 'draft', 'files': []}}),
        outcome_event('turn/end', 3, reason={'kind': 'blocked'}),
    ]}
    outcome = _turn_outcome(context, None)
    assert outcome['status'] == 'not-delivered' and outcome['file_requested']
    context['events'][1]['data']['source']['delivery']['files'] = [{'path': 'report.pending.pdf', 'phase': 'draft'}]
    assert _turn_outcome(context, None)['status'] == 'partial'


def test_review_keeps_unfulfilled_report_goal_after_crop_with_bounded_no_file_observation():
    context = {'failed_turn': 1, 'omitted_event_count': 4, 'events': [], 'failure_analysis': {
        'turn': 1, 'turn_result': 'blocked', 'delivery_result': 'draft', 'failures': [], 'outcome': {
            'goal_request': {'event_seq': 1, 'text': '给我一份企业全景报告'}, 'file_requested': True, 'files': []}}}
    assert _turn_outcome(context, _failure_analysis(context))['status'] == 'not-delivered'


@pytest.mark.parametrize('request_text', [
    '宁波展奕捷精密机械有限公司，高新技术企业专精特新，双报告',
    '宁波海格亚阿科比轴承有限公司，研发中心可行性分析报告',
    '杭州示例有限公司 高企可行性报告。',
])
def test_review_keeps_shorthand_company_project_report_goal_without_a_file(request_text):
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': request_text}]}},
        outcome_event('user/message', 2, source={'kind': 'plugin:gongchuang-policy-gate', 'delivery': {'turn': 1, 'phase': 'draft', 'files': []}}),
        outcome_event('turn/end', 3, reason={'kind': 'blocked'}),
    ]}
    outcome = _turn_outcome(context, None)
    assert outcome['file_requested'] is True
    assert outcome['status'] == 'not-delivered'


@pytest.mark.parametrize('request_text', [
    '阅读宁波海格亚阿科比轴承有限公司，研发中心可行性分析报告',
    '解释这份宁波海格亚阿科比轴承有限公司，研发中心可行性分析报告',
    '分析这份宁波海格亚阿科比轴承有限公司，研发中心可行性分析报告',
    '宁波展奕捷精密机械有限公司，高新技术企业专精特新，双报告吗？',
    '宁波展奕捷精密机械有限公司，是否支持高新技术企业专精特新双报告',
    '宁波展奕捷精密机械有限公司，不要生成高新技术企业专精特新双报告',
    '你能生成宁波海格亚阿科比轴承有限公司的研发中心可行性分析报告吗？',
])
def test_review_does_not_infer_shorthand_creation_from_existing_reports_or_questions(request_text):
    context = {'failed_turn': 1, 'events': [
        {'type': 'user/message', 'seq': 1, 'data': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': request_text}]}},
        outcome_event('user/message', 2, source={'kind': 'plugin:gongchuang-policy-gate', 'delivery': {'turn': 1, 'phase': 'draft', 'files': []}}),
        outcome_event('turn/end', 3, reason={'kind': 'blocked'}),
    ]}
    outcome = _turn_outcome(context, None)
    assert outcome['file_requested'] is False
    assert outcome['status'] == 'blocked'


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
