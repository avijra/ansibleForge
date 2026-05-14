"""Unit tests for ansible_forge.dep_manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ansible_forge.dep_manager import (
    _MODULE_TO_PIP,
    COLLECTION_DEPS,
    _is_package_installed,
    ensure_collection_deps,
    ensure_packages,
    guess_pip_package,
    parse_missing_module,
)


class TestCollectionDepsMapping:
    """Validate COLLECTION_DEPS mapping integrity."""

    def test_all_values_are_lists(self):
        for collection, deps in COLLECTION_DEPS.items():
            assert isinstance(deps, list), f"{collection} has non-list deps"

    def test_all_packages_are_strings(self):
        for collection, deps in COLLECTION_DEPS.items():
            for dep in deps:
                assert isinstance(dep, str), f"{collection} has non-string dep: {dep}"

    def test_no_empty_package_names(self):
        for collection, deps in COLLECTION_DEPS.items():
            for dep in deps:
                assert dep.strip(), f"{collection} has empty package name"

    def test_major_clouds_present(self):
        assert "amazon.aws" in COLLECTION_DEPS
        assert "azure.azcollection" in COLLECTION_DEPS
        assert "google.cloud" in COLLECTION_DEPS
        assert "kubernetes.core" in COLLECTION_DEPS
        assert "redhat.openshift" in COLLECTION_DEPS

    def test_aws_has_boto3(self):
        assert "boto3" in COLLECTION_DEPS["amazon.aws"]
        assert "botocore" in COLLECTION_DEPS["amazon.aws"]

    def test_azure_has_identity(self):
        assert "azure-identity" in COLLECTION_DEPS["azure.azcollection"]

    def test_k8s_has_kubernetes(self):
        assert "kubernetes" in COLLECTION_DEPS["kubernetes.core"]

    def test_mapping_has_at_least_30_collections(self):
        assert len(COLLECTION_DEPS) >= 30


class TestModuleToPipMapping:
    """Validate _MODULE_TO_PIP mapping."""

    def test_common_mappings(self):
        assert _MODULE_TO_PIP["yaml"] == "pyyaml"
        assert _MODULE_TO_PIP["OpenSSL"] == "pyopenssl"
        assert _MODULE_TO_PIP["winrm"] == "pywinrm"
        assert _MODULE_TO_PIP["Crypto"] == "pycryptodome"

    def test_cloud_mappings(self):
        assert _MODULE_TO_PIP["boto3"] == "boto3"
        assert _MODULE_TO_PIP["kubernetes"] == "kubernetes"
        assert _MODULE_TO_PIP["docker"] == "docker"


class TestParseMissingModule:
    """Test parse_missing_module regex patterns."""

    def test_standard_module_not_found(self):
        assert parse_missing_module("ModuleNotFoundError: No module named 'boto3'") == "boto3"

    def test_import_error(self):
        assert parse_missing_module("ImportError: No module named 'kubernetes'") == "kubernetes"

    def test_ansible_library_format(self):
        assert parse_missing_module(
            "Failed to import the required Python library (docker)"
        ) == "docker"

    def test_nested_module(self):
        assert parse_missing_module(
            "ModuleNotFoundError: No module named 'azure.identity'"
        ) == "azure"

    def test_double_quotes(self):
        assert parse_missing_module(
            'ModuleNotFoundError: No module named "pyvmomi"'
        ) == "pyvmomi"

    def test_no_match_returns_none(self):
        assert parse_missing_module("Connection refused") is None
        assert parse_missing_module("") is None
        assert parse_missing_module("Playbook completed successfully") is None

    def test_none_input(self):
        assert parse_missing_module(None) is None  # type: ignore[arg-type]

    def test_multiline_error(self):
        error = (
            "TASK [Create EC2 instance] ***\n"
            "fatal: [localhost]: FAILED! => \n"
            "ModuleNotFoundError: No module named 'boto3'\n"
            "The above exception was the direct cause..."
        )
        assert parse_missing_module(error) == "boto3"

    def test_requires_library_pattern(self):
        error = "This module requires the paramiko Python module"
        assert parse_missing_module(error) == "paramiko"


class TestGuessPipPackage:
    """Test guess_pip_package mapping logic."""

    def test_known_mapping(self):
        assert guess_pip_package("yaml") == "pyyaml"
        assert guess_pip_package("OpenSSL") == "pyopenssl"
        assert guess_pip_package("winrm") == "pywinrm"
        assert guess_pip_package("Crypto") == "pycryptodome"
        assert guess_pip_package("PIL") == "pillow"

    def test_unknown_falls_back_to_module_name(self):
        assert guess_pip_package("requests") == "requests"
        assert guess_pip_package("flask") == "flask"
        assert guess_pip_package("totally_unknown_pkg") == "totally_unknown_pkg"

    def test_cloud_modules(self):
        assert guess_pip_package("boto3") == "boto3"
        assert guess_pip_package("kubernetes") == "kubernetes"
        assert guess_pip_package("hcloud") == "hcloud"


class TestIsPackageInstalled:
    """Test package installation detection."""

    def test_not_installed_empty_dir(self, tmp_path: Path):
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            assert not _is_package_installed("boto3")

    def test_installed_as_directory(self, tmp_path: Path):
        (tmp_path / "boto3").mkdir()
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            assert _is_package_installed("boto3")

    def test_installed_with_version_suffix(self, tmp_path: Path):
        (tmp_path / "boto3-1.28.0.dist-info").mkdir()
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            assert _is_package_installed("boto3")

    def test_normalized_name_match(self, tmp_path: Path):
        (tmp_path / "azure_identity").mkdir()
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            assert _is_package_installed("azure-identity")

    def test_no_dir_returns_false(self):
        with patch(
            "ansible_forge.dep_manager.MANAGED_SITE_PACKAGES",
            Path("/nonexistent/path/xyz"),
        ):
            assert not _is_package_installed("anything")


class TestEnsurePackages:
    """Test the ensure_packages async function."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_success(self):
        ok, msg = await ensure_packages([], reason="test")
        assert ok
        assert msg == ""

    @pytest.mark.asyncio
    async def test_all_installed_skips(self, tmp_path: Path):
        (tmp_path / "boto3").mkdir()
        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            ok, msg = await ensure_packages(["boto3"], reason="test")
            assert ok
            assert msg == ""

    @pytest.mark.asyncio
    async def test_installs_missing(self, tmp_path: Path):
        with (
            patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path),
            patch("ansible_forge.dep_manager._resolve_installer") as mock_resolver,
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            mock_resolver.return_value = ("/usr/bin/uv", ["pip", "install", "--target"])
            proc = AsyncMock()
            proc.communicate.return_value = (b"OK", b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            ok, msg = await ensure_packages(["boto3", "botocore"], reason="test")
            assert ok
            assert "boto3" in msg

    @pytest.mark.asyncio
    async def test_handles_timeout(self, tmp_path: Path):
        with (
            patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path),
            patch("ansible_forge.dep_manager._resolve_installer") as mock_resolver,
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            mock_resolver.return_value = ("/usr/bin/uv", ["pip", "install", "--target"])

            ok, msg = await ensure_packages(["boto3"], reason="test")
            assert not ok
            assert "timed out" in msg


class TestEnsureCollectionDeps:
    """Test ensure_collection_deps logic."""

    @pytest.mark.asyncio
    async def test_known_collection(self):
        with patch("ansible_forge.dep_manager.ensure_packages", new_callable=AsyncMock) as mock:
            mock.return_value = (True, "Installed")
            ok, msg = await ensure_collection_deps("amazon.aws")
            assert ok
            args = mock.call_args[0][0]
            assert "boto3" in args

    @pytest.mark.asyncio
    async def test_unknown_collection(self):
        ok, msg = await ensure_collection_deps("unknown.xyz")
        assert ok
        assert msg == ""

    @pytest.mark.asyncio
    async def test_versioned_collection_name(self):
        with patch("ansible_forge.dep_manager.ensure_packages", new_callable=AsyncMock) as mock:
            mock.return_value = (True, "Installed")
            ok, msg = await ensure_collection_deps("amazon.aws:7.0.0")
            assert ok
            mock.assert_called_once()


class TestEnsurePackagesIntegration:
    """Integration test that actually runs uv/pip (skipped if neither is available)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_install_requests(self, tmp_path: Path):
        """Actually install a small package to verify the full flow."""
        import shutil

        if not (shutil.which("uv") or shutil.which("pip3") or shutil.which("pip")):
            pytest.skip("No package installer available")

        with patch("ansible_forge.dep_manager.MANAGED_SITE_PACKAGES", tmp_path):
            ok, msg = await ensure_packages(["six"], reason="integration-test")
            assert ok
            assert "six" in msg
            # Verify the package was actually installed
            assert any(
                p.name.startswith("six") for p in tmp_path.iterdir()
            ), f"six not found in {list(tmp_path.iterdir())}"
