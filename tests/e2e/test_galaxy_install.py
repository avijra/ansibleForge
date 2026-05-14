"""E2E test: verify galaxy install triggers SDK dep installation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ansible_forge.tools.base import ToolResult, ToolStatus


@pytest.mark.e2e
class TestGalaxyInstallDeps:
    """Test that manage_galaxy install hooks into dep_manager."""

    @pytest.mark.asyncio
    async def test_install_triggers_ensure_collection_deps(self):
        """After a successful galaxy install, ensure_collection_deps should be called."""
        with (
            patch(
                "ansible_forge.tools.galaxy_manager.GalaxyManager._run_galaxy",
                new_callable=AsyncMock,
            ) as mock_galaxy,
            patch(
                "ansible_forge.dep_manager.ensure_collection_deps",
                new_callable=AsyncMock,
            ) as mock_deps,
        ):
            mock_galaxy.return_value = (0, "amazon.aws installed", "")
            mock_deps.return_value = (True, "Installed Python dependencies: boto3, botocore, jmespath")

            from ansible_forge.tools.galaxy_manager import GalaxyManager

            gm = GalaxyManager()
            result = await gm._install("amazon.aws", "")

            assert result.status == ToolStatus.SUCCESS
            assert "installed successfully" in result.output
            assert "boto3" in result.output
            mock_deps.assert_called_once_with("amazon.aws")

    @pytest.mark.asyncio
    async def test_install_failure_skips_deps(self):
        """Failed galaxy installs should not attempt dep installation."""
        with (
            patch(
                "ansible_forge.tools.galaxy_manager.GalaxyManager._run_galaxy",
                new_callable=AsyncMock,
            ) as mock_galaxy,
            patch(
                "ansible_forge.dep_manager.ensure_collection_deps",
                new_callable=AsyncMock,
            ) as mock_deps,
        ):
            mock_galaxy.return_value = (1, "", "ERROR: collection not found")

            from ansible_forge.tools.galaxy_manager import GalaxyManager

            gm = GalaxyManager()
            result = await gm._install("nonexistent.collection", "")

            assert result.status == ToolStatus.ERROR
            mock_deps.assert_not_called()

    @pytest.mark.asyncio
    async def test_dep_install_failure_does_not_fail_galaxy(self):
        """If dep installation fails, the galaxy install should still report success."""
        with (
            patch(
                "ansible_forge.tools.galaxy_manager.GalaxyManager._run_galaxy",
                new_callable=AsyncMock,
            ) as mock_galaxy,
            patch(
                "ansible_forge.dep_manager.ensure_collection_deps",
                new_callable=AsyncMock,
            ) as mock_deps,
        ):
            mock_galaxy.return_value = (0, "community.vmware installed", "")
            mock_deps.return_value = (False, "Failed to install pyvmomi: network error")

            from ansible_forge.tools.galaxy_manager import GalaxyManager

            gm = GalaxyManager()
            result = await gm._install("community.vmware", "")

            assert result.status == ToolStatus.SUCCESS
            assert "installed successfully" in result.output
            assert "Failed to install pyvmomi" in result.output
