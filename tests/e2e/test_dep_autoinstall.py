"""E2E test: verify dep_manager auto-installs SDK when a collection is installed."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ansible_forge.dep_manager import (
    COLLECTION_DEPS,
    ensure_collection_deps,
    ensure_packages,
    guess_pip_package,
    parse_missing_module,
)


@pytest.mark.e2e
class TestDepAutoInstall:
    """Test the dep_manager auto-install flow end-to-end."""

    def test_collection_deps_mapping_has_major_clouds(self):
        assert "amazon.aws" in COLLECTION_DEPS
        assert "azure.azcollection" in COLLECTION_DEPS
        assert "google.cloud" in COLLECTION_DEPS
        assert "kubernetes.core" in COLLECTION_DEPS
        assert "redhat.openshift" in COLLECTION_DEPS
        assert "community.vmware" in COLLECTION_DEPS
        assert "community.docker" in COLLECTION_DEPS

    def test_parse_missing_module_standard(self):
        error = "ModuleNotFoundError: No module named 'boto3'"
        assert parse_missing_module(error) == "boto3"

    def test_parse_missing_module_import_error(self):
        error = "ImportError: No module named 'kubernetes'"
        assert parse_missing_module(error) == "kubernetes"

    def test_parse_missing_module_ansible_format(self):
        error = "Failed to import the required Python library (boto3)"
        assert parse_missing_module(error) == "boto3"

    def test_parse_missing_module_nested(self):
        error = "ModuleNotFoundError: No module named 'azure.identity'"
        assert parse_missing_module(error) == "azure"

    def test_parse_missing_module_no_match(self):
        error = "Connection refused to host 10.0.0.1"
        assert parse_missing_module(error) is None

    def test_guess_pip_package_known(self):
        assert guess_pip_package("yaml") == "pyyaml"
        assert guess_pip_package("OpenSSL") == "pyopenssl"
        assert guess_pip_package("winrm") == "pywinrm"

    def test_guess_pip_package_unknown_falls_back(self):
        assert guess_pip_package("somepackage") == "somepackage"

    @pytest.mark.asyncio
    async def test_ensure_collection_deps_known(self):
        """Verify ensure_collection_deps calls ensure_packages for known collections."""
        with patch("ansible_forge.dep_manager.ensure_packages", new_callable=AsyncMock) as mock_ep:
            mock_ep.return_value = (True, "Installed boto3")
            ok, msg = await ensure_collection_deps("amazon.aws")
            assert ok
            mock_ep.assert_called_once()
            call_args = mock_ep.call_args[0][0]
            assert "boto3" in call_args
            assert "botocore" in call_args

    @pytest.mark.asyncio
    async def test_ensure_collection_deps_unknown(self):
        """Unknown collections should return True with no action."""
        ok, msg = await ensure_collection_deps("nonexistent.collection")
        assert ok
        assert msg == ""

    @pytest.mark.asyncio
    async def test_ensure_packages_already_installed(self, tmp_path: Path):
        """Packages that already exist in site-packages should be skipped."""
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            (tmp_path / "boto3").mkdir()
            ok, msg = await ensure_packages(["boto3"], reason="test")
            assert ok
            assert msg == ""

    @pytest.mark.asyncio
    async def test_ensure_packages_installs_missing(self, tmp_path: Path):
        """Missing packages should trigger an installer subprocess."""
        with (
            patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path),
            patch("ansible_forge.dep_manager._resolve_installer") as mock_resolver,
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc,
        ):
            mock_resolver.return_value = ("/usr/bin/uv", ["pip", "install", "--target"])
            proc_instance = AsyncMock()
            proc_instance.communicate.return_value = (b"Successfully installed", b"")
            proc_instance.returncode = 0
            mock_proc.return_value = proc_instance

            ok, msg = await ensure_packages(["boto3"], reason="test")
            assert ok
            assert "boto3" in msg

    @pytest.mark.asyncio
    async def test_ensure_packages_handles_failure(self, tmp_path: Path):
        """Failed installs should return False with error message."""
        with (
            patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path),
            patch("ansible_forge.dep_manager._resolve_installer") as mock_resolver,
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc,
        ):
            mock_resolver.return_value = ("/usr/bin/uv", ["pip", "install", "--target"])
            proc_instance = AsyncMock()
            proc_instance.communicate.return_value = (b"", b"ERROR: No matching distribution")
            proc_instance.returncode = 1
            mock_proc.return_value = proc_instance

            ok, msg = await ensure_packages(["nonexistent-pkg"], reason="test")
            assert not ok
            assert "Failed" in msg
