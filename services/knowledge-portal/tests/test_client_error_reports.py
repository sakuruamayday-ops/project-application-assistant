from contextlib import closing
from uuid import uuid4
import base64
import json
import re
import tracemalloc
import pytest
from fastapi.testclient import TestClient
from test_portal import load_app
from app.client_error_reports import feedback_category, feedback_subject
from app import client_error_reports


def report():
    return dict(request_id=str(uuid4()), client_version='0.4.8-workbench.1', skill_version='1.6.20', platform='darwin-arm64', occurred_at='2026-09-22T08:00:00Z', module='workbench', code='GC-REPORT-WORKBENCH', summary='unsafe raw model body must not survive', steps='点击生成失败\napi_key=sk-syntheticsecret123\n密码：syntheticpassword\n/Users/customer/private.docx\nC:\\Customers\\private.docx')


def setup(tmp_path):
    module = load_app(tmp_path)
    client = TestClient(module.app)
    client.post('/setup', data=dict(setup_key='setup-secret', username='owner', password='synthetic-password-123'))
    login = client.post('/v1/client-login', json=dict(client_id=module.CLIENT_AUTHORIZATION_ID, client_version='0.4.8', platform='macos', device_id='gcd_'+'a'*48, device_name='Test device', username='owner', password='synthetic-password-123'))
    assert login.status_code == 200, login.text
    headers={'Authorization':'Bearer '+login.json()['access_token'], module.DEVICE_ID_HEADER:'gcd_'+'a'*48}
    return module, client, headers


def upgrade_context():
    return {'failed_turn': 2, 'omitted_event_count': 0, 'events': [
        {'type': 'tool/result', 'data': {'turn': 1, 'message': {'isError': True,
            'content': [{'type': 'text', 'text': 'Request timed out'}]}}},
        {'type': 'turn/end', 'data': {'turn': 1, 'reason': {'kind': 'error', 'error': {'code': 'TIMEOUT'}}}},
        {'type': 'turn/start', 'data': {'turn': 2}},
        {'type': 'turn/end', 'data': {'turn': 2, 'reason': {'kind': 'error', 'error': {
            'code': 'GC-ACCOUNT-UPGRADE', 'message': '最低支持版本为 V0.7.0，请前往团队门户升级',
        }}}},
    ]}


@pytest.mark.parametrize('version,with_analysis', [('0.6.3', False), ('0.6.5', True)])
def test_upgrade_classification_uses_current_events_in_old_and_new_clients(version, with_analysis):
    context = upgrade_context()
    if with_analysis:
        context['failure_analysis'] = {'turn': 2, 'failures': [{'category': 'precondition',
            'stage': 'client-upgrade', 'code': 'GC-ACCOUNT-UPGRADE', 'status': 'expected-block'}]}
    diagnostic = {**report(), 'code': 'GC-AUTO-FAILURE', 'client_version': version,
                  'conversation_context': json.dumps(context)}
    assert feedback_category(diagnostic) == 'other'


@pytest.mark.parametrize('kind', ['tool/result', 'tool/ptc-dispatch', 'delivery-failed', 'unattributed-tool'])
def test_upgrade_does_not_hide_a_real_current_failure_or_trust_claimed_expected_status(kind):
    context = upgrade_context()
    context['failure_analysis'] = {'turn': 2, 'failures': [], 'primary_failure': {
        'category': 'precondition', 'stage': 'client-upgrade', 'status': 'expected-block'}}
    if kind == 'delivery-failed':
        event = {'type': 'user/message', 'data': {'source': {'kind': 'plugin:gongchuang-policy-gate',
            'delivery': {'turn': 2, 'phase': 'failed'}}}}
    elif kind == 'tool/ptc-dispatch':
        event = {'type': kind, 'data': {'turn': 2, 'isError': True,
            'content': [{'type': 'text', 'text': 'Request timed out'}]}}
    else:
        event = {'type': 'tool/result', 'data': {'turn': 2, 'message': {'isError': True,
            'content': [{'type': 'text', 'text': 'Request timed out'}]}}}
        if kind == 'unattributed-tool':
            event['data'].pop('turn')
    context['events'].insert(-1, event)
    assert feedback_category({'code': 'GC-AUTO-FAILURE', 'conversation_context': json.dumps(context)}) == 'bug'


@pytest.mark.parametrize('code', ['GC-REPORT-WORKBENCH', 'GC-REPORT-CONVERSATION', 'GC-ACCOUNT-UPGRADE'])
def test_manual_reports_and_outer_upgrade_code_are_not_automatically_reclassified(code):
    assert feedback_category({'code': code, 'conversation_context': json.dumps(upgrade_context())}) == 'bug'


@pytest.mark.parametrize('code', [None, 'GC-ACCOUNT-TIMEOUT', 'GC-ACCOUNT-UPGRADE-FAILED'])
def test_upgrade_text_or_client_analysis_without_the_exact_terminal_code_remains_a_bug(code):
    context = upgrade_context()
    context['events'][-1]['data']['reason']['error'] = {
        'code': code, 'message': 'GC-ACCOUNT-UPGRADE: 最低支持版本为 V0.7.0',
    }
    context['failure_analysis'] = {'turn': 2, 'failures': [{'code': 'GC-ACCOUNT-UPGRADE',
        'stage': 'client-upgrade', 'category': 'precondition', 'status': 'expected-block'}]}
    assert feedback_category({'code': 'GC-AUTO-FAILURE', 'conversation_context': json.dumps(context)}) == 'bug'


def test_uncertain_or_cropped_context_is_not_reclassified_as_an_upgrade_stop():
    context = upgrade_context()
    context['omitted_event_count'] = 1
    assert feedback_category({'code': 'GC-AUTO-FAILURE', 'conversation_context': json.dumps(context)}) == 'bug'
    context.pop('failed_turn')
    assert feedback_category({'code': 'GC-AUTO-FAILURE', 'conversation_context': json.dumps(context)}) == 'bug'
    assert feedback_category({'code': 'GC-AUTO-FAILURE', 'conversation_context': '[]'}) == 'bug'


@pytest.mark.parametrize('code,category,title', [
    ('GC-AUTO-RECOVERED', 'other', '客户端过程问题已恢复'),
    ('GC-AUTO-PROTECTION', 'other', '客户端文件保护提示'),
    ('GC-AUTO-CANCELLED-WITH-ISSUES', 'bug', '客户端任务已取消（含过程异常）'),
    ('GC-AUTO-DELIVERED-WITH-ISSUES', 'bug', '客户端已有输出（含过程异常）'),
    ('GC-AUTO-INTERRUPTED', 'bug', '客户端任务中断（结果待确认）'),
])
def test_automatic_outcome_metadata_does_not_parse_conversation_context(monkeypatch, code, category, title):
    def unexpected_parse(_value):
        raise AssertionError('Outcome presentation must use saved metadata')
    monkeypatch.setattr(client_error_reports.json, 'loads', unexpected_parse)
    diagnostic = {'code': code, 'conversation_context': 'large context is not needed for this classification'}
    assert feedback_category(diagnostic) == category
    assert feedback_subject(diagnostic, category) == title + ' · ' + code


@pytest.mark.parametrize('code', ['GC-AUTO-RECOVERED-FAKE', 'GC-AUTO-PROTECTION-FAILED', 'GC-AUTO-CANCELLED'])
def test_unknown_automatic_code_is_not_reclassified(code):
    diagnostic = {'code': code}
    assert feedback_category(diagnostic) == 'bug'
    assert feedback_subject(diagnostic, 'bug') == '客户端错误 · ' + code


def test_automatic_outcomes_preserve_diagnostics_and_pending_review_with_accurate_list_titles(tmp_path):
    module, client, headers = setup(tmp_path)
    cases = [
        ('GC-AUTO-RECOVERED', 'other', '客户端过程问题已恢复'),
        ('GC-AUTO-PROTECTION', 'other', '客户端文件保护提示'),
        ('GC-AUTO-CANCELLED-WITH-ISSUES', 'bug', '客户端任务已取消（含过程异常）'),
        ('GC-AUTO-DELIVERED-WITH-ISSUES', 'bug', '客户端已有输出（含过程异常）'),
        ('GC-AUTO-INTERRUPTED', 'bug', '客户端任务中断（结果待确认）'),
        ('GC-AUTO-FAILURE', 'bug', '客户端错误'),
    ]
    context = {'failed_turn': 1, 'events': [
        {'type': 'tool/ptc-dispatch', 'data': {'turn': 1, 'isError': True, 'error': 'synthetic retained failure'}},
        {'type': 'turn/end', 'data': {'turn': 1, 'reason': {'kind': 'completed'}}},
    ]}
    receipts = []
    for code, category, title in cases:
        payload = {**report(), 'module': 'conversation', 'code': code, 'steps': '', 'conversation_context': json.dumps(context)}
        response = client.post('/v1/client-error-reports', json=payload, headers=headers)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert client.post('/v1/client-error-reports', json=payload, headers=headers).json() == receipt
        receipts.append((receipt['report_id'], title))
        with closing(module.database()) as db:
            row = db.execute('SELECT category,status,resolved_at,subject,content FROM feedback_messages WHERE id=?', (receipt['report_id'],)).fetchone()
            assert tuple(row)[:4] == (category, 'pending', None, title + ' · ' + code)
            stored = json.loads(db.execute('SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=?', (receipt['report_id'],)).fetchone()[0])
            assert stored['code'] == code
            assert json.loads(stored['conversation_context']) == context
            assert row['content'] == stored['summary']
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    page = client.get('/feedback')
    assert page.status_code == 200
    for report_id, title in receipts:
        assert title in page.text
        exported = client.get(f'/admin/feedback/{report_id}/diagnostic').json()
        assert json.loads(exported['conversation_context']) == context


def test_expected_upgrade_intake_keeps_pending_diagnostics_idempotence_and_attachments(tmp_path):
    module, client, headers = setup(tmp_path)
    context = upgrade_context()
    fid = str(uuid4())
    context['diagnostic_files'] = [{'file_id': fid, 'name': 'synthetic.txt', 'size': 3, 'status': 'pending'}]
    payload = {**report(), 'code': 'GC-AUTO-FAILURE', 'module': 'conversation', 'client_version': '0.6.3',
               'conversation_context': json.dumps(context)}
    response = client.post('/v1/client-error-reports', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert client.post('/v1/client-error-reports', json=payload, headers=headers).json() == receipt
    with closing(module.database()) as db:
        row = db.execute('SELECT category,status,resolved_at,subject FROM feedback_messages WHERE id=?', (receipt['report_id'],)).fetchone()
        assert tuple(row) == ('other', 'pending', None, '客户端升级拦截 · GC-ACCOUNT-UPGRADE')
        assert db.execute('SELECT COUNT(*) FROM client_error_reports').fetchone()[0] == 1
        stored = json.loads(db.execute('SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=?', (receipt['report_id'],)).fetchone()[0])
        assert stored['request_id'] == payload['request_id']
        assert stored['code'] == 'GC-AUTO-FAILURE'
        assert json.loads(stored['conversation_context']) == context
    chunk = dict(file_id=fid, name='synthetic.txt', size=3, offset=0, data=base64.b64encode(b'abc').decode())
    assert client.post(f"/v1/client-error-reports/{receipt['report_id']}/files", json=chunk, headers=headers).json() == {'next_offset': 3, 'complete': True}
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    assert '客户端升级拦截 · GC-ACCOUNT-UPGRADE' in client.get('/feedback').text
    assert client.get(f"/admin/feedback/{receipt['report_id']}/diagnostic").json() == stored
    assert client.get(f"/admin/feedback/{receipt['report_id']}/diagnostic-files/{fid}").content == b'abc'


def test_real_auth_idempotence_redaction_and_admin_export(tmp_path):
    module, client, headers = setup(tmp_path)
    payload=report()
    response=client.post('/v1/client-error-reports', json=payload, headers=headers)
    assert response.status_code==200, response.text
    receipt=response.json()
    assert client.post('/v1/client-error-reports', json=payload, headers=headers).json()==receipt
    with closing(module.database()) as db:
        assert db.execute('SELECT COUNT(*) FROM client_error_reports').fetchone()[0]==1
        text=db.execute('SELECT diagnostic_json FROM client_error_reports').fetchone()[0]
        user_id=db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        assert db.execute('SELECT user_id FROM feedback_messages').fetchone()[0]==user_id
    for secret in ['syntheticsecret123','syntheticpassword','private.docx','unsafe raw model']:
        assert secret not in text
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    page=client.get('/feedback')
    assert '客户端诊断' in page.text and '0.4.8-workbench.1' in page.text
    download=client.get(f"/admin/feedback/{receipt['report_id']}/diagnostic")
    assert download.status_code==200 and download.json()['request_id']==payload['request_id']
    assert client.post(f"/admin/feedback/{receipt['report_id']}", data=dict(feedback_status='resolved',admin_note='tested',csrf_token='wrong')).status_code==403
    csrf=re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response=client.post(f"/admin/feedback/{receipt['report_id']}", data=dict(feedback_status='reviewing',admin_note='triaged',csrf_token=csrf),follow_redirects=False)
    assert response.status_code==303
    assert 'triaged' in client.get('/feedback?feedback_query=GC-REPORT').text
    # Make the same authenticated web account a normal member; admin export must close.
    with closing(module.database()) as db:
        db.execute("UPDATE users SET is_admin=0 WHERE username='owner'");db.commit()
    assert client.get(f"/admin/feedback/{receipt['report_id']}/diagnostic", follow_redirects=False).status_code in (403,303)


def test_rejects_unknown_fields_device_spoofing_and_invalid_token(tmp_path):
    module, client, headers=setup(tmp_path)
    payload=report()
    assert client.post('/v1/client-error-reports',json=payload).status_code==401
    assert client.post('/v1/client-error-reports',json=payload,headers={**headers,'Authorization':'Bearer invalid'}).status_code==401
    assert client.post('/v1/client-error-reports',json=payload,headers={**headers,module.DEVICE_ID_HEADER:'gcd_'+'b'*48}).status_code==401
    for extra in [dict(user_id=99),dict(logs='model private text'),dict(steps='x'*3001)]:
        assert client.post('/v1/client-error-reports',json={**payload,**extra},headers=headers).status_code==422
    with closing(module.database()) as db:
        user_id=db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
    personal=module.ensure_personal_access_token(user_id)
    assert client.post('/v1/client-error-reports',json=payload,headers={'Authorization':'Bearer '+personal}).status_code==403


def test_body_limit_and_rate_limit_keep_retry_available(tmp_path):
    module, client, headers = setup(tmp_path)
    assert client.post('/v1/client-error-reports', content='x'*48_000_001, headers=headers).status_code == 413
    first = report()
    saved = client.post('/v1/client-error-reports', json=first, headers=headers).json()
    for _ in range(29):
        assert client.post('/v1/client-error-reports', json=report(), headers=headers).status_code == 200
    assert client.post('/v1/client-error-reports', json=report(), headers=headers).status_code == 429
    assert client.post('/v1/client-error-reports', json=first, headers=headers).json() == saved


def test_registered_member_cannot_read_another_report_or_export(tmp_path):
    module, client, headers = setup(tmp_path)
    receipt = client.post('/v1/client-error-reports', json=report(), headers=headers).json()
    with closing(module.database()) as db:
        now=module.isoformat(module.utc_now())
        uid=db.execute('INSERT INTO users(username,real_name,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)',('other','Other',module.password_hasher.hash('other-password-123'),0,now)).lastrowid
        db.execute("INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,registered_at) VALUES (?,?,'registered',?,?,?)",('Other','ER-OTHER',uid,now,now));db.commit()
    client.cookies.clear()
    assert client.post('/login',data=dict(username='other',password='other-password-123'),follow_redirects=False).status_code==303
    page=client.get('/feedback')
    assert page.status_code==200 and '客户端诊断 #'+str(receipt['report_id']) not in page.text
    assert client.get(f"/admin/feedback/{receipt['report_id']}/diagnostic",follow_redirects=False).status_code==403


def test_full_context_survives_admin_export_with_credentials_redacted(tmp_path):
    module, client, headers = setup(tmp_path)
    payload = report()
    payload['conversation_context'] = json.dumps({'events': [{'type': 'user/message', 'data': {'text': 'first message'}}, {'type': 'tool/result', 'data': {'password': 'context-secret', 'text': 'failed'}}, {'type': 'turn/end', 'data': {'status': 'cancelled'}}]})
    response = client.post('/v1/client-error-reports', json=payload, headers=headers)
    assert response.status_code == 200
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    exported = client.get(f"/admin/feedback/{response.json()['report_id']}/diagnostic").json()
    context = json.loads(exported['conversation_context'])
    assert len(context['events']) == 3
    assert context['events'][0]['data']['text'] == 'first message'
    assert context['events'][1]['data']['password'] == '[已隐藏凭据]'
    assert context['events'][2]['data']['status'] == 'cancelled'
    assert 'context-secret' not in exported['conversation_context']
    assert client.post('/v1/client-error-reports', json={**report(), 'conversation_context': 'invalid JSON'}, headers=headers).status_code == 422


def test_attachment_resume_admin_download_and_review_route(tmp_path):
    module, client, headers = setup(tmp_path)
    receipt = client.post('/v1/client-error-reports', json=report(), headers=headers).json()
    rid, fid = receipt['report_id'], str(uuid4())
    payload = dict(file_id=fid, name='synthetic.txt', size=6, offset=0, data=base64.b64encode(b'abc').decode())
    endpoint = f'/v1/client-error-reports/{rid}/files'
    assert client.post(endpoint, json=payload, headers=headers).json() == dict(next_offset=3, complete=False)
    assert client.post(endpoint, json=payload, headers=headers).json() == dict(next_offset=3, complete=False)
    assert client.post(endpoint, json={**payload, 'offset': 3, 'data': base64.b64encode(b'def').decode()}, headers=headers).json() == dict(next_offset=6, complete=True)
    assert client.post(endpoint, content='x' * 2_000_001, headers=headers).status_code == 413
    assert client.post(f'/v1/client-error-reports/{rid+100}/files', json=payload, headers=headers).status_code == 404
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    download = client.get(f'/admin/feedback/{rid}/diagnostic-files/{fid}')
    assert download.status_code == 200 and download.content == b'abcdef'
    assert 'synthetic.txt' in client.get('/admin/client-diagnostic-reviews').text
    assert '错误复盘与诊断附件' in client.get('/feedback').text
    with closing(module.database()) as db:
        db.execute("UPDATE users SET is_admin=0 WHERE username='owner'"); db.commit()
    assert client.get(f'/admin/feedback/{rid}/diagnostic-files/{fid}', follow_redirects=False).status_code in (403, 303)
    assert client.get('/admin/client-diagnostic-reviews', follow_redirects=False).status_code in (403, 303)


def test_feedback_list_excludes_large_context_but_preserves_export(tmp_path):
    module, client, _ = setup(tmp_path)
    payload = report()
    payload['conversation_context'] = json.dumps({
        'events': [{'text': 'retained-context-marker ' * 90_000}],
    })
    diagnostic_json = json.dumps(payload)
    with closing(module.database()) as db:
        owner = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        now = module.isoformat(module.utc_now())
        report_ids = []
        for _ in range(51):
            rid = db.execute(
                "INSERT INTO feedback_messages(user_id,category,subject,content,status,created_at,updated_at) VALUES (?,'bug','客户端错误 GC-REPORT-WORKBENCH','点击生成失败','pending',?,?)",
                (owner, now, now),
            ).lastrowid
            db.execute(
                'INSERT INTO client_error_reports(feedback_id,user_id,request_id,diagnostic_json) VALUES (?,?,?,?)',
                (rid, owner, str(uuid4()), diagnostic_json),
            )
            report_ids.append(rid)
        db.commit()
    client.post('/login', data=dict(username='owner', password='synthetic-password-123'))
    tracemalloc.start()
    try:
        page = client.get('/feedback')
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert page.status_code == 200
    assert page.text.count('<summary>客户端诊断 #') == 51
    assert '0.4.8-workbench.1' in page.text
    assert 'retained-context-marker' not in page.text
    feedback_html = page.text.split('<section id="feedback"', 1)[1].split('</section>', 1)[0]
    assert len(feedback_html.encode()) < 200_000
    assert len(page.content) < 1_000_000
    assert peak < 32 * 1024 * 1024
    assert '客户端诊断 #' in client.get('/feedback?feedback_query=GC-REPORT').text
    exported = client.get(f'/admin/feedback/{report_ids[-1]}/diagnostic')
    assert exported.status_code == 200
    assert exported.json()['conversation_context'] == payload['conversation_context']
