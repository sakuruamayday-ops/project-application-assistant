"""Synthetic original-upload transport, member access and report-lifecycle isolation."""
import base64
import hashlib
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app import client_attachments, client_reports
from test_client_reports import create as create_report, login, setup, upload as upload_report


def attachment(data=b'original-file', **changes):
    return {
        'request_id': str(uuid4()), 'filename': 'original.png', 'size_bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(), 'uploaded_at': '2026-10-20T02:00:00Z',
        'client_version': '0.7.6', 'session_id': 'synthetic-session', 'task_title': 'Synthetic task',
        **changes,
    }


def create(client, headers, payload):
    response = client.post('/v1/client-attachments', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, headers, attachment_id, data, offset=0):
    return client.post(f'/v1/client-attachments/{attachment_id}/content', headers=headers,
        json={'offset': offset, 'content_base64': base64.b64encode(data).decode()})


def test_original_bytes_resume_integrity_and_retained_download(tmp_path):
    module, client, headers = setup(tmp_path)
    data = b'\xff\xd8\xfforiginal-image-metadata\x00\x80\xff\xd9'
    payload = attachment(data, filename='camera-original.JPG', task_title='<script>private task</script>')
    initial = create(client, headers, payload)
    aid = initial['attachment_id']
    assert initial == {'attachment_id': aid, 'next_offset': 0, 'complete': False}
    assert create(client, headers, payload) == initial
    assert client.post('/v1/client-attachments', headers=headers, json={**payload, 'filename': 'changed.jpg'}).status_code == 409
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    assert client.get(f'/client-attachments/{aid}/download').status_code == 404
    assert upload(client, headers, aid, data[:7]).json() == {'next_offset': 7, 'complete': False}
    assert upload(client, headers, aid, data[:7]).json() == {'next_offset': 7, 'complete': False}
    assert create(client, headers, payload)['next_offset'] == 7
    assert upload(client, headers, aid, b'x' * (len(data) - 7), 7).status_code == 422
    assert create(client, headers, payload)['next_offset'] == 0
    assert upload(client, headers, aid, data).json() == {'next_offset': len(data), 'complete': True}
    assert upload(client, headers, aid, b'overwrite').json()['complete'] is True
    for _ in range(2):
        downloaded = client.get(f'/client-attachments/{aid}/download')
        assert downloaded.content == data
        assert downloaded.headers['x-gongchuang-attachment-sha256'] == payload['sha256']
        assert downloaded.headers['content-type'] == 'application/octet-stream'
        assert 'attachment;' in downloaded.headers['content-disposition']
        assert downloaded.headers['cache-control'] == 'private, no-store'
    path = client_reports.file_path(module.DATA_DIR / 'client-attachments', aid)
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.parent.parent.stat().st_mode & 0o777 == 0o700
    page = client.get('/client-attachments')
    assert page.status_code == 200 and 'camera-original.JPG' in page.text
    assert '<script>private task</script>' not in page.text
    assert '&lt;script&gt;private task&lt;/script&gt;' in page.text
    assert '上传时间（北京时间）' in page.text and '2026-10-20 10:00:00' in page.text
    assert '上传原件' in client.get('/downloads').text
    path.write_bytes(b'corrupt-original')
    assert client.get(f'/client-attachments/{aid}/download').status_code == 409


def test_real_password_device_and_minimum_version_are_required(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    payload = attachment()
    assert client.post('/v1/client-attachments', json=payload).status_code == 401
    assert client.post('/v1/client-attachments', json=payload, headers={**headers, module.DEVICE_ID_HEADER: 'gcd_' + 'b' * 48}).status_code == 401
    with closing(module.database()) as connection:
        uid = connection.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
    personal = module.ensure_personal_access_token(uid)
    assert client.post('/v1/client-attachments', json=payload, headers={'Authorization': 'Bearer ' + personal}).status_code == 403
    assert client.post('/v1/client-attachments', json=payload, headers={**headers, module.CLIENT_VERSION_HEADER: '0.7.5'}).status_code == 409
    for version in ['0.7.5', 'invalid']:
        assert client.post('/v1/client-attachments', json={**payload, 'client_version': version}, headers=headers).status_code == 409
    aid = create(client, headers, payload)['attachment_id']
    monkeypatch.setattr(module, 'MINIMUM_SUPPORTED_CLIENT_VERSION', '0.7.7')
    assert upload(client, headers, aid, b'original-file').status_code == 409
    client.cookies.clear()
    assert client.get('/client-attachments', follow_redirects=False).status_code == 303
    assert client.get(f'/client-attachments/{aid}/download', follow_redirects=False).status_code == 303


def test_empty_original_file_matches_real_user_upload_admission(tmp_path):
    module, client, headers = setup(tmp_path)
    payload = attachment(b'', filename='empty-user-upload.txt')
    initial = create(client, headers, payload)
    aid = initial['attachment_id']
    assert initial == {'attachment_id': aid, 'next_offset': 0, 'complete': True}
    assert create(client, headers, payload) == initial
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    downloaded = client.get(f'/client-attachments/{aid}/download')
    assert downloaded.status_code == 200 and downloaded.content == b''
    assert client_reports.file_path(module.DATA_DIR / 'client-attachments', aid).is_file()
    invalid = client.post('/v1/client-attachments', headers=headers,
        json=attachment(b'', sha256=hashlib.sha256(b'not-empty').hexdigest()))
    assert invalid.status_code == 422


def test_members_upload_only_and_admin_alone_sees_originals_and_uploader_account(tmp_path):
    module, client, owner = setup(tmp_path)
    payload = attachment(filename='owner-original.pdf')
    owner_id = create(client, owner, payload)['attachment_id']
    assert upload(client, owner, owner_id, b'original-file').status_code == 200
    with closing(module.database()) as connection:
        now = module.isoformat(module.utc_now())
        uid = connection.execute('INSERT INTO users(username,real_name,password_hash,is_admin,created_at) VALUES (?,?,?,?,?)',
            ('attachment-member', 'Synthetic Member', module.password_hasher.hash('synthetic-password-123'), 0, now)).lastrowid
        connection.execute("INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,registered_at) VALUES (?,?,'registered',?,?,?)",
            ('Synthetic Member', 'ATTACHMENT-MEMBER', uid, now, now))
        connection.commit()
    member = login(module, client, 'attachment-member', 'b')
    assert upload(client, member, owner_id, b'original-file').status_code == 404
    member_id = create(client, member, {**payload, 'filename': 'member-original.csv', 'task_title': None})['attachment_id']
    assert member_id != owner_id
    assert upload(client, member, member_id, b'original-file').status_code == 200
    client.cookies.clear()
    client.post('/login', data={'username': 'attachment-member', 'password': 'synthetic-password-123'})
    page = client.get('/client-attachments')
    assert page.status_code == 403
    assert client.get(f'/client-attachments/{owner_id}/download').status_code == 403
    assert client.get(f'/client-attachments/{member_id}/download').status_code == 403
    assert 'href="/client-attachments"' not in client.get('/downloads').text
    client.cookies.clear()
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    page = client.get('/client-attachments')
    assert page.status_code == 200
    assert 'member-original.csv' in page.text and 'owner-original.pdf' in page.text
    assert 'Synthetic Member' in page.text and 'attachment-member' in page.text
    assert 'synthetic-session' in page.text
    assert client.get(f'/client-attachments/{member_id}/download').content == b'original-file'
    assert 'href="/client-attachments"' in client.get('/downloads').text


def test_metadata_rejects_paths_chat_and_arbitrary_extra_fields(tmp_path):
    _, client, headers = setup(tmp_path)
    payload = attachment()
    for change in [dict(filename='../original.pdf'), dict(filename='C:\\original.pdf'),
                   dict(local_path='/private/original.pdf'), dict(chat='not collected'),
                   dict(extra={'any': 'value'}), dict(user_id=999),
                   dict(session_id='/private/session'), dict(size_bytes=2**53),
                   dict(sha256='wrong'), dict(uploaded_at='2026-10-20T02:00:00')]:
        response = client.post('/v1/client-attachments', json={**payload, **change}, headers=headers)
        assert response.status_code == 422, response.text
    # User uploads are broader than business-report finals, including originals without extensions.
    for filename in ['original.txt', 'source.js', 'original.eml', 'sheet.csv', 'photo.webp', '无后缀']:
        assert create(client, headers, attachment(filename=filename))['complete'] is False


def test_body_chunk_and_declared_size_limits(tmp_path):
    _, client, headers = setup(tmp_path)
    assert client.post('/v1/client-attachments', content='x' * 32_001, headers=headers).status_code == 413
    aid = create(client, headers, attachment())['attachment_id']
    assert client.post(f'/v1/client-attachments/{aid}/content', content='x' * 2_000_001, headers=headers).status_code == 413
    assert client.post('/v1/client-attachments/-1/content', content='x' * 2_000_001, headers=headers).status_code == 413
    assert client.post(f'/v1/client-attachments/{aid}/content', json={'offset': 0, 'content_base64': '!'}, headers=headers).status_code == 422
    assert upload(client, headers, aid, b'x' * (1024**2 + 1)).status_code == 422
    assert upload(client, headers, aid, b'longer-than-declared-original').status_code == 422
    assert upload(client, headers, aid, b'original-file').json()['complete'] is True


def test_original_metadata_accepts_100_mib_and_rejects_one_byte_more_without_large_files(tmp_path):
    module, client, headers = setup(tmp_path)
    payload = attachment(size_bytes=100 * 1024**2, filename='boundary-original.bin')
    receipt = create(client, headers, payload)
    assert receipt == {'attachment_id': receipt['attachment_id'], 'next_offset': 0, 'complete': False}
    rejected = client.post('/v1/client-attachments', headers=headers,
        json=attachment(size_bytes=100 * 1024**2 + 1, filename='too-large-original.bin'))
    assert rejected.status_code == 422
    assert not client_reports.file_path(module.DATA_DIR / 'client-attachments', receipt['attachment_id']).exists()
    with closing(module.database()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM client_attachments').fetchone()[0] == 1


def test_prior_oversized_pending_registration_refuses_more_content(tmp_path):
    module, client, headers = setup(tmp_path)
    aid = create(client, headers, attachment())['attachment_id']
    with closing(module.database()) as connection:
        connection.execute('UPDATE client_attachments SET size_bytes=? WHERE id=?', (100 * 1024**2 + 1, aid))
        connection.commit()
    assert upload(client, headers, aid, b'first').status_code == 422
    assert not client_reports.file_path(module.DATA_DIR / 'client-attachments', aid).exists()


def test_attachment_storage_reserve_retry_and_symlink_rejection(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    aid = create(client, headers, attachment())['attachment_id']
    root = module.DATA_DIR / 'client-attachments'
    path = client_reports.file_path(root, aid)
    usage = client_reports.shutil.disk_usage
    monkeypatch.setattr(client_reports.shutil, 'disk_usage', lambda _path: type('Usage', (), {'free': 2 * 1024**3})())
    assert upload(client, headers, aid, b'original-file').status_code == 422
    assert not path.exists()
    monkeypatch.setattr(client_reports.shutil, 'disk_usage', usage)
    target = tmp_path / 'preserved-original.txt'
    target.write_bytes(b'must remain')
    path.symlink_to(target)
    assert upload(client, headers, aid, b'original-file').status_code == 422
    assert target.read_bytes() == b'must remain'
    # Use a new request to retry normally, leaving the synthetic symlink intact for inspection.
    second_id = create(client, headers, attachment())['attachment_id']
    assert upload(client, headers, second_id, b'original-file').json()['complete'] is True


def test_report_collection_and_cleanup_never_include_original_attachments(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    aid = create(client, headers, attachment())['attachment_id']
    assert upload(client, headers, aid, b'original-file').json()['complete'] is True
    rid = create_report(client, headers)['report_id']
    assert upload_report(client, headers, rid, b'abcdef').json()['complete'] is True
    original = client_reports.file_path(module.DATA_DIR / 'client-attachments', aid)
    report_root = module.DATA_DIR / 'client-reports'
    report_path = client_reports.file_path(report_root, rid)
    kept = tmp_path / 'preserved-cleanup-test-report.pdf'
    def preserve_cleanup_bytes(path):
        assert path == report_path
        path.rename(kept)
    monkeypatch.setattr(Path, 'unlink', preserve_cleanup_bytes)
    with closing(module.database()) as connection:
        assert [row['report_id'] for row in client_reports.list_reports(connection, undownloaded_only=True)] == [rid]
        assert connection.execute('SELECT COUNT(*) FROM client_attachments').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM client_error_reports').fetchone()[0] == 0
        client_reports.acknowledge_download(connection, rid)
        assert client_reports.cleanup_report(connection, report_root, rid)['deleted'] == 1
        attachments = client_attachments.list_attachments(connection)
        assert len(attachments) == 1 and attachments[0]['attachment_id'] == aid
        assert 'cleaned_at' not in attachments[0]
    assert original.read_bytes() == b'original-file'
    assert kept.read_bytes() == b'abcdef'
