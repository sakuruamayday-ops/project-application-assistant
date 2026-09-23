from contextlib import closing
from uuid import uuid4
import json
import re
from fastapi.testclient import TestClient
from test_portal import load_app


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
