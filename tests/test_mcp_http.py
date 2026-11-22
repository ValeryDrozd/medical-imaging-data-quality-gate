import asyncio
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from quality_gate.core import validate_batch
from quality_gate.mcp_server import server
from quality_gate.models import BatchResult

ROOT = Path(__file__).resolve().parents[1]


def test_streamable_http_batch_and_request_boundary() -> None:
    async def check_transport() -> None:
        app = server.streamable_http_app()
        base_url = "http://127.0.0.1:8000"
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as http,
        ):
            invalid_origin = await http.post(
                "/mcp", json={}, headers={"Origin": "https://example.com"}
            )
            assert invalid_origin.status_code == 403
            invalid_host = await http.post("/mcp", json={}, headers={"Host": "example.com"})
            assert invalid_host.status_code == 421

            async with (
                streamable_http_client(f"{base_url}/mcp", http_client=http) as (read, write, _),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                result = await client.call_tool("validate_batch", {"confidence_threshold": 0.38})
                assert not result.isError
                expected = validate_batch(
                    ROOT / "task_description/batch.json",
                    ROOT / "task_description/taxonomy.json",
                    confidence_threshold=0.38,
                )
                assert BatchResult.model_validate(result.structuredContent) == expected

    asyncio.run(check_transport())
