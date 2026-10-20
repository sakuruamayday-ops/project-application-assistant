"""Final-report upload, ownership and collector checks using synthetic accounts and files."""
import base64
import hashlib
import json
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import client_reports
from test_portal import load_app


def setup(tmp_path):
    module = load_app(tmp_path)
    client = TestClient(module.app)
    client.post('/setup', data=dict(setup_key='setup-secret', username='owner', password='synthetic-password-123'))
    return module, client, login(module, client, 'owner', 'a')


def login(module, client, username, device):
    response = client.post('/v1/client-login', json=dict(
        client_id=module.CLIENT_AUTHORIZATION_ID, client_version='0.7.6', platform='macos',
        device_id='gcd_' + device * 48, device_name='Synthetic report device',
        username=username, password='synthetic-password-123',
    ))
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token'],
            module.DEVICE_ID_HEADER: 'gcd_' + device * 48, module.CLIENT_VERSION_HEADER: '0.7.6'}


def report(data=b'abcdef', **changes):
    return dict(request_id=str(uuid4()), filename='synthetic-report.pdf', size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), generated_at='2026-10-20T02:00:00Z',
        title='Synthetic final report', company_name=None, skill_name='enterprise-profile',
        skill_version='1.6.20', client_version='0.7.6', report_kind='business-analysis',
        stage='final', final_reason='Original task marked this file as final', **changes)


def upload(client, headers, rid, data, offset=0):
    return client.post(f'/v1/client-reports/{rid}/content', headers=headers,
        json={'offset': offset, 'content_base64': base64.b64encode(data).decode()})


def create(client, headers, payload=None):
    response = client.post('/v1/client-reports', headers=headers, json=payload or report())
    assert response.status_code == 200, response.text
    return response.json()


def test_resume_idempotence_integrity_and_completed_download(tmp_path):
    module, client, headers = setup(tmp_path)
    payload = report()
    initial = create(client, headers, payload)
    rid = initial['report_id']
    assert initial == {'report_id': rid, 'next_offset': 0, 'complete': False}
    assert create(client, headers, payload) == initial
    assert client.post('/v1/client-reports', headers=headers, json={**payload, 'title': 'New revision'}).status_code == 409
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    assert client.get(f'/client-reports/{rid}/download').status_code == 404
    assert upload(client, headers, rid, b'abc').json() == {'next_offset': 3, 'complete': False}
    assert upload(client, headers, rid, b'abc').json() == {'next_offset': 3, 'complete': False}
    assert create(client, headers, payload)['next_offset'] == 3
    assert upload(client, headers, rid, b'bad', 3).status_code == 422
    assert create(client, headers, payload)['next_offset'] == 0
    assert client.get(f'/client-reports/{rid}/download').status_code == 404
    assert upload(client, headers, rid, b'abcdef').json() == {'next_offset': 6, 'complete': True}
    assert upload(client, headers, rid, b'changed').json() == {'next_offset': 6, 'complete': True}
    assert create(client, headers, payload) == {'report_id': rid, 'next_offset': 6, 'complete': True}
    assert create(client, {**headers, module.CLIENT_VERSION_HEADER: '0.7.7'}, payload)['report_id'] == rid
    downloaded = client.get(f'/client-reports/{rid}/download')
    assert downloaded.content == b'abcdef'
    assert downloaded.headers['x-gongchuang-report-sha256'] == payload['sha256']
    assert 'attachment;' in downloaded.headers['content-disposition']
    assert client.get('/client-reports').status_code == 200
    assert 'Synthetic final report' in client.get('/client-reports').text
    assert '定稿报告' in client.get('/downloads').text
    with closing(module.database()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM client_reports').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM client_error_reports').fetchone()[0] == 0
    client_reports.file_path(module.DATA_DIR / 'client-reports', rid).write_bytes(b'xxxxxx')
    assert client.get(f'/client-reports/{rid}/download').status_code == 409


def test_real_auth_version_checks_and_rejected_inputs(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    payload = report()
    assert client.post('/v1/client-reports', json=payload).status_code == 401
    assert client.post('/v1/client-reports', json=payload, headers={**headers, module.DEVICE_ID_HEADER: 'gcd_' + 'b' * 48}).status_code == 401
    with closing(module.database()) as connection:
        uid = connection.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
    personal = module.ensure_personal_access_token(uid)
    assert client.post('/v1/client-reports', json=payload, headers={'Authorization': 'Bearer ' + personal}).status_code == 403
    assert client.post('/v1/client-reports', json=payload, headers={**headers, module.CLIENT_VERSION_HEADER: '0.7.5'}).status_code == 409
    assert client.post('/v1/client-reports', json={**payload, 'client_version': '0.7.5'}, headers=headers).status_code == 409
    for extra in [dict(stage='draft'), dict(report_kind='chat'), dict(local_path='/tmp/private.pdf'),
                  dict(chat='private text'), dict(user_id=999), dict(filename='../report.pdf'),
                  dict(filename='C:\\private.pdf'), dict(size_bytes=256 * 1024 * 1024 + 1),
                  dict(filename='analysis.js'), dict(filename='original.eml'),
                  dict(sha256='not-a-digest'), dict(generated_at='2026-10-20T02:00:00')]:
        assert client.post('/v1/client-reports', json={**payload, **extra}, headers=headers).status_code == 422
    assert client.post('/v1/client-reports', content='x' * 32_001, headers=headers).status_code == 413
    rid = create(client, headers, payload)['report_id']
    assert client.post(f'/v1/client-reports/{rid}/content', content='x' * 2_000_001, headers=headers).status_code == 413
    assert client.post(f'/v1/client-reports/{rid}/content', json={'offset': 0, 'content_base64': '!'}, headers=headers).status_code == 422
    assert upload(client, headers, rid, b'abcdefg').status_code == 422
    monkeypatch.setattr(module, 'MINIMUM_SUPPORTED_CLIENT_VERSION', '0.7.7')
    assert upload(client, headers, rid, b'abcdef').status_code == 409


def test_member_isolation_and_admin_read_access(tmp_path):
    module, client, owner = setup(tmp_path)
    payload = report()
    owner_id = create(client, owner, payload)['report_id']
    assert upload(client, owner, owner_id, b'abcdef').status_code == 200
    with closing(module.database()) as connection:
        now = module.isoformat(module.utc_now())
        uid = connection.execute('INSERT INTO users(username,real_name,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)',
            ('member', 'Synthetic Member', module.password_hasher.hash('synthetic-password-123'), 0, now)).lastrowid
        connection.execute("INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,registered_at) VALUES (?,?,'registered',?,?,?)",
            ('Synthetic Member', 'REPORT-MEMBER', uid, now, now))
        connection.commit()
    member = login(module, client, 'member', 'b')
    assert upload(client, member, owner_id, b'abcdef').status_code == 404
    member_id = create(client, member, {**payload, 'title': 'Member final'})['report_id']
    assert member_id != owner_id
    assert upload(client, member, member_id, b'abcdef').status_code == 200
    client.cookies.clear()
    client.post('/login', data={'username': 'member', 'password': 'synthetic-password-123'})
    page = client.get('/client-reports')
    assert 'Member final' in page.text and 'Synthetic final report' not in page.text
    assert client.get(f'/client-reports/{owner_id}/download').status_code == 404
    assert client.get(f'/client-reports/{member_id}/download').content == b'abcdef'
    client.cookies.clear()
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    page = client.get('/client-reports')
    assert 'Member final' in page.text and 'Synthetic final report' in page.text
    assert client.get(f'/client-reports/{member_id}/download').content == b'abcdef'


def test_collector_list_export_acknowledge_and_dry_run_only(tmp_path):
    module, client, headers = setup(tmp_path)
    payload = report()
    rid = create(client, headers, payload)['report_id']
    create(client, headers)  # An incomplete file must never enter the collector list.
    assert upload(client, headers, rid, b'abcdef').status_code == 200
    with closing(module.database()) as connection:
        db_path = connection.execute('PRAGMA database_list').fetchone()[2]
    script = Path(__file__).resolve().parents[1] / 'scripts/client_reports.py'
    root = module.DATA_DIR / 'client-reports'
    command = [sys.executable, str(script), '--database', db_path, '--root', str(root)]
    def run(*args):
        return subprocess.run([*command, *args], capture_output=True)
    listing = json.loads(run('list').stdout)
    assert listing['next_offset'] is None and len(listing['reports']) == 1
    assert listing['reports'][0]['report_id'] == rid
    assert listing['reports'][0]['request_id'] == payload['request_id']
    assert listing['reports'][0]['member_name'] == 'owner'
    exported = run('export', '--report-id', str(rid))
    assert exported.returncode == 0 and exported.stdout == b'abcdef' and not exported.stderr
    first = run('acknowledge', '--report-id', str(rid))
    assert first.returncode == 0
    assert run('acknowledge', '--report-id', str(rid)).stdout == first.stdout
    assert json.loads(run('list').stdout)['reports'] == []
    assert run('cleanup').returncode != 0
    preview = run('cleanup', '--dry-run')
    assert preview.returncode == 0 and json.loads(preview.stdout)['deleted'] == 0
    assert json.loads(preview.stdout)['candidates'][0]['report_id'] == rid
    assert client_reports.file_path(root, rid).read_bytes() == b'abcdef'


def test_report_storage_rejects_symlinks(tmp_path):
    module, client, headers = setup(tmp_path)
    rid = create(client, headers)['report_id']
    path = client_reports.file_path(module.DATA_DIR / 'client-reports', rid)
    path.parent.mkdir(parents=True)
    target = tmp_path / 'must-remain.txt'
    target.write_bytes(b'original')
    path.symlink_to(target)
    assert upload(client, headers, rid, b'abcdef').status_code == 422
    assert target.read_bytes() == b'original'


def test_upload_keeps_existing_disk_reserve_and_can_retry(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    rid = create(client, headers)['report_id']
    usage = client_reports.shutil.disk_usage
    monkeypatch.setattr(client_reports.shutil, 'disk_usage', lambda _path: type('Usage', (), {'free': 2 * 1024**3})())
    assert upload(client, headers, rid, b'abcdef').status_code == 422
    assert not client_reports.file_path(module.DATA_DIR / 'client-reports', rid).exists()
    monkeypatch.setattr(client_reports.shutil, 'disk_usage', usage)
    assert upload(client, headers, rid, b'abcdef').json() == {'next_offset': 6, 'complete': True}


def test_cleanup_requires_confirmed_identity_preserves_metadata_and_repeats_without_touching_other_files(tmp_path, monkeypatch, capsys):
    module, client, headers = setup(tmp_path)
    payload = report()
    rid = create(client, headers, payload)['report_id']
    assert upload(client, headers, rid, b'abcdef').status_code == 200
    root = module.DATA_DIR / 'client-reports'
    path = client_reports.file_path(root, rid)
    kept = tmp_path / 'preserved-cleanup-fixture.pdf'
    unrelated = tmp_path / 'unrelated-document.pdf'
    unrelated.write_bytes(b'unrelated-original')
    calls = []
    def preserve_instead_of_unlink(target):
        # Exercise the unlink decision while retaining every fixture byte for this development task.
        assert target == path
        calls.append(target)
        target.rename(kept)
    monkeypatch.setattr(Path, 'unlink', preserve_instead_of_unlink)
    with closing(module.database()) as connection:
        with pytest.raises(client_reports.ReportConflict):
            client_reports.cleanup_report(connection, root, rid)
        client_reports.acknowledge_download(connection, rid)
        with pytest.raises(client_reports.ReportConflict):
            client_reports.cleanup_report(connection, tmp_path, rid)
        assert client_reports.cleanup_report(connection, root, rid, dry_run=True)['deleted'] == 0
        assert path.read_bytes() == b'abcdef' and not calls
        assert connection.execute('SELECT cleanup_requested_at FROM client_reports WHERE id=?', (rid,)).fetchone()[0] is None
        from scripts import client_reports as collector_cli
        database_path = connection.execute('PRAGMA database_list').fetchone()[2]
        assert collector_cli.main(['--database', database_path, '--root', str(root), 'cleanup', '--report-id', str(rid)]) == 0
        cleaned = json.loads(capsys.readouterr().out)
        assert cleaned['report_id'] == rid and cleaned['deleted'] == 1 and cleaned['cleaned_at']
        assert client_reports.cleanup_report(connection, root, rid) == {**cleaned, 'deleted': 0}
        assert client_reports.acknowledge_download(connection, rid)['downloaded_at']
        assert connection.execute('SELECT COUNT(*) FROM client_reports').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM client_error_reports').fetchone()[0] == 0
        with pytest.raises(client_reports.ReportNotFound):
            client_reports.completed_file(connection, root, rid)
    assert len(calls) == 1 and kept.read_bytes() == b'abcdef'
    assert unrelated.read_bytes() == b'unrelated-original'


def test_cleanup_does_not_repeat_download_integrity_checks_and_recovers_recorded_intent(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    payload = report()
    rid = create(client, headers, payload)['report_id']
    assert upload(client, headers, rid, b'abcdef').status_code == 200
    root = module.DATA_DIR / 'client-reports'
    path = client_reports.file_path(root, rid)
    calls = []
    monkeypatch.setattr(Path, 'unlink', lambda target: calls.append(target))
    with closing(module.database()) as connection:
        client_reports.acknowledge_download(connection, rid)
        path.write_bytes(b'changed')
        def forbidden_integrity_read(*args, **kwargs):
            raise AssertionError('download acknowledgement and cleanup must not reread size or SHA-256')
        monkeypatch.setattr(client_reports, 'completed_file', forbidden_integrity_read)
        client_reports.acknowledge_download(connection, rid)
        assert client_reports.cleanup_report(connection, root, rid, dry_run=True)['deleted'] == 0
        assert not calls
        path.rename(tmp_path / 'preserved-changed-fixture.pdf')
        with pytest.raises(client_reports.ReportNotFound):
            client_reports.cleanup_report(connection, root, rid)
        connection.execute('UPDATE client_reports SET cleanup_requested_at=? WHERE id=?', ('2026-10-20T03:00:00+00:00', rid))
        connection.commit()
        result = client_reports.cleanup_report(connection, root, rid)
        assert result['deleted'] == 0 and result['cleaned_at']
        assert not calls
