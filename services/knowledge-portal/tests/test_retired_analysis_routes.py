"""The portal keeps knowledge and identity consumers while retiring server business analysis."""
import asyncio
from contextlib import closing

from test_client_reports import setup


def test_lifecycle_rest_is_authenticated_but_never_runs_the_business_engine(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('retired business engine must not execute')
    monkeypatch.setattr(module, 'enterprise_lifecycle_decision', forbidden)
    assert client.post('/v1/enterprise-lifecycle/decide', json={}).status_code == 401
    assert client.post('/v1/enterprise-lifecycle/decide', headers=headers, json={}).status_code == 410
    assert client.get('/v1/me', headers=headers).status_code == 200
    assert client.get('/readyz').status_code == 200


def test_mcp_retains_search_consumers_without_advertising_lifecycle_business_decisions(tmp_path):
    module, _, _ = setup(tmp_path)
    tools = asyncio.run(module.knowledge_mcp.list_tools())
    names = {tool.name for tool in tools}
    assert 'enterprise_lifecycle_decision' not in names
    assert {'knowledge_search', 'knowledge_document', 'policy_search', 'public_list_search',
            'three_first_analysis', 'project_catalog_match', 'recognition_search',
            'enterprise_identity_lineage_lookup', 'knowledge_service_status'} <= names
    result = asyncio.run(module.knowledge_search('小巨人', limit=2))
    assert result['results']


def test_portal_and_cockpit_keep_knowledge_status_and_downloads_without_answering_controls(tmp_path):
    module, client, _ = setup(tmp_path)
    client.post('/login', data={'username': 'owner', 'password': 'synthetic-password-123'})
    for path in ('/portal', '/cockpit'):
        response = client.get(path)
        assert response.status_code == 200
        assert '知识服务态势' in response.text
        assert '下载共创客户端' in response.text
        for removed in ('id="assistant-form"', 'data-question=', 'user_api_key', '开始答疑', '知识库智能答疑'):
            assert removed not in response.text
    script = client.get('/static/portal.js').text
    assert '/assistant/answer' not in script
    assert 'sessionStorage.getItem' not in script and 'sessionStorage.setItem' not in script
    with closing(module.database()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM assistant_usage').fetchone()[0] == 0
