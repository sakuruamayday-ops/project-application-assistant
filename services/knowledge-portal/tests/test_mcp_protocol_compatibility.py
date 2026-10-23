"""Exercise the mounted, authenticated MCP endpoint across both protocol eras."""

import asyncio
from contextlib import closing

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from test_client_reports import setup
from three_step_install_fixture import run_live_portal


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_live_mcp_keeps_legacy_clients_and_serves_modern_clients(tmp_path, mode):
    portal, _, _ = setup(tmp_path)
    with closing(portal.database()) as connection:
        user_id = connection.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
    token = portal.ensure_personal_access_token(user_id)

    async def exercise(base_url):
        async with httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=10,
        ) as http_client:
            transport = streamable_http_client(f"{base_url}/mcp/", http_client=http_client)
            async with Client(transport, mode=mode, read_timeout_seconds=10) as client:
                if mode == "auto":
                    assert client.protocol_version == "2026-07-28"
                else:
                    assert client.protocol_version < "2026-07-28"
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"knowledge_search", "knowledge_document", "knowledge_service_status"} <= names
                assert "enterprise_lifecycle_decision" not in names
                result = await client.call_tool("knowledge_search", {"query": "产业链", "limit": 1})
                assert not result.is_error
                assert result.structured_content["results"]
                wrong_type = await client.call_tool("knowledge_search", {"query": {}})
                assert wrong_type.is_error
                assert (await client.call_tool("knowledge_service_status")).structured_content["connected"]

    with run_live_portal(portal) as base_url:
        asyncio.run(exercise(base_url))
