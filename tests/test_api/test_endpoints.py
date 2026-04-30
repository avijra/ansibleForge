"""Tests for settings, knowledge, and execute API routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestLLMSettingsEndpoints:
    @pytest.mark.asyncio
    async def test_get_llm_settings_response_shape(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/settings/llm")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) >= {
            "provider",
            "model",
            "api_key_set",
            "api_base",
            "temperature",
            "max_tokens",
            "source",
        }
        assert isinstance(data["provider"], str)
        assert isinstance(data["model"], str)
        assert isinstance(data["api_key_set"], bool)
        assert data["api_base"] is None or isinstance(data["api_base"], str)
        assert isinstance(data["temperature"], (int, float))
        assert isinstance(data["max_tokens"], int)
        assert data["source"] in ("runtime", "env")

    @pytest.mark.asyncio
    async def test_put_and_delete_llm_settings(self, async_client: AsyncClient) -> None:
        before = (await async_client.get("/api/v1/settings/llm")).json()
        new_temp = 0.88 if before["temperature"] != 0.88 else 0.77

        put = await async_client.put(
            "/api/v1/settings/llm",
            json={"temperature": new_temp},
        )
        assert put.status_code == 200
        put_data = put.json()
        assert put_data["temperature"] == new_temp

        after_put = (await async_client.get("/api/v1/settings/llm")).json()
        assert after_put["temperature"] == new_temp

        deleted = await async_client.delete("/api/v1/settings/llm")
        assert deleted.status_code == 200

        after_delete = (await async_client.get("/api/v1/settings/llm")).json()
        assert after_delete["temperature"] == before["temperature"]


class TestKnowledgeEndpoints:
    @pytest.mark.asyncio
    async def test_knowledge_stats_shape(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/knowledge/stats")
        assert response.status_code == 200
        data = response.json()
        assert "stats" in data
        assert "recent_errors" in data
        assert isinstance(data["recent_errors"], list)

    @pytest.mark.asyncio
    async def test_knowledge_graph_shape(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/knowledge/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)


class TestExecuteEndpoint:
    @pytest.mark.asyncio
    async def test_execute_localhost_playbook_check_mode(
        self,
        async_client: AsyncClient,
        sample_playbook: str,
    ) -> None:
        response = await async_client.post(
            "/api/v1/execute",
            json={
                "playbook_content": sample_playbook,
                "mode": "check",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "output" in data
        assert "data" in data
        assert isinstance(data["data"], dict)
        assert data["status"] in ("success", "error", "needs_approval")
