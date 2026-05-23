"""Tests for SecretRequester tool guards."""

from __future__ import annotations

import pytest

from ansible_forge.tools.secret_requester import SecretRequester, _looks_like_non_secret


class TestNonSecretDetection:
    @pytest.mark.parametrize("name", [
        "AWS_DEFAULT_REGION",
        "cluster_base_domain",
        "cluster_name",
        "control_plane_instance_type",
        "worker_count",
        "worker_instance_type",
        "vpc_id",
        "subnet_name",
        "ami_id",
        "project_name",
        "availability_zone",
        "dns_name",
    ])
    def test_blocks_non_secret_names(self, name: str) -> None:
        assert _looks_like_non_secret(name) is True

    @pytest.mark.parametrize("name", [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "ssh_private_key",
        "pull_secret",
        "api_token",
        "db_password",
        "ansible_ssh_key",
        "openshift_pull_secret",
    ])
    def test_allows_real_secrets(self, name: str) -> None:
        assert _looks_like_non_secret(name) is False


class TestSecretRequesterExecute:
    @pytest.mark.asyncio
    async def test_rejects_non_secret_name(self) -> None:
        tool = SecretRequester()
        result = await tool.execute(
            name="cluster_base_domain",
            description="The base domain for the cluster",
        )
        assert result.status.value == "error"
        assert "BLOCKED" in (result.error or "")

    @pytest.mark.asyncio
    async def test_allows_real_secret(self) -> None:
        tool = SecretRequester()
        result = await tool.execute(
            name="AWS_ACCESS_KEY_ID",
            description="AWS access key",
        )
        assert result.status.value == "needs_approval"
        assert result.data.get("secret_request") is True

    @pytest.mark.asyncio
    async def test_duplicate_secret_returns_ok(self) -> None:
        from ansible_forge.safety.secret_vault import SecretVault
        vault = SecretVault()
        session_vault = vault.for_session("test-dup-check")
        session_vault.store("api_token", "super-secret-value", "test token")

        old_instance = SecretVault._instance
        SecretVault._instance = vault
        try:
            tool = SecretRequester()
            result = await tool.execute(
                name="api_token",
                description="API token",
                _session_id="test-dup-check",
            )
            assert result.status.value == "success"
            assert "already stored" in result.output
        finally:
            SecretVault._instance = old_instance
            vault.destroy_session("test-dup-check")
