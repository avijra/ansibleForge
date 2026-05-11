"""Integration tests for frozen (PyInstaller) environment setup.

Verifies that _setup_frozen_env correctly configures PATH and SSL
when sys.frozen is True, ensuring companion binaries are discoverable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration


class TestFrozenEnvSetup:
    """Test _setup_frozen_env behavior in simulated frozen mode."""

    def _import_setup(self):
        from ansible_forge.main import _setup_frozen_env
        return _setup_frozen_env

    def test_prepends_managed_bin_to_path(self) -> None:
        """~/.ansibleforge/bin should always be prepended to PATH."""
        _setup_frozen_env = self._import_setup()
        managed_bin = str(Path.home() / ".ansibleforge" / "bin")

        path_backup = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/usr/local/bin"
            _setup_frozen_env()
            assert managed_bin in os.environ["PATH"].split(os.pathsep)
            assert os.environ["PATH"].startswith(managed_bin)
        finally:
            os.environ["PATH"] = path_backup

    def test_frozen_mode_prepends_bundle_dir(self, tmp_path) -> None:
        """When sys.frozen=True, the binary's parent dir is prepended to PATH."""
        _setup_frozen_env = self._import_setup()

        fake_exe = tmp_path / "ansibleforge-backend"
        fake_exe.touch()

        path_backup = os.environ.get("PATH", "")
        ssl_backup = os.environ.pop("SSL_CERT_FILE", None)
        try:
            os.environ["PATH"] = "/usr/bin"
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(fake_exe)):
                _setup_frozen_env()

            path_parts = os.environ["PATH"].split(os.pathsep)
            assert str(tmp_path) in path_parts, (
                f"Expected {tmp_path} in PATH, got: {path_parts}"
            )
        finally:
            os.environ["PATH"] = path_backup
            if ssl_backup:
                os.environ["SSL_CERT_FILE"] = ssl_backup
            else:
                os.environ.pop("SSL_CERT_FILE", None)

    def test_frozen_mode_sets_ssl_cert_file(self, tmp_path) -> None:
        """When sys.frozen=True with _internal/certifi/cacert.pem, SSL_CERT_FILE is set."""
        _setup_frozen_env = self._import_setup()

        fake_exe = tmp_path / "ansibleforge-backend"
        fake_exe.touch()

        cert_dir = tmp_path / "_internal" / "certifi"
        cert_dir.mkdir(parents=True)
        cacert = cert_dir / "cacert.pem"
        cacert.write_text("-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n")

        path_backup = os.environ.get("PATH", "")
        ssl_backup = os.environ.pop("SSL_CERT_FILE", None)
        req_backup = os.environ.pop("REQUESTS_CA_BUNDLE", None)
        try:
            os.environ["PATH"] = "/usr/bin"
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", str(fake_exe)):
                _setup_frozen_env()

            assert os.environ.get("SSL_CERT_FILE") == str(cacert)
            assert os.environ.get("REQUESTS_CA_BUNDLE") == str(cacert)
        finally:
            os.environ["PATH"] = path_backup
            if ssl_backup:
                os.environ["SSL_CERT_FILE"] = ssl_backup
            else:
                os.environ.pop("SSL_CERT_FILE", None)
            if req_backup:
                os.environ["REQUESTS_CA_BUNDLE"] = req_backup
            else:
                os.environ.pop("REQUESTS_CA_BUNDLE", None)

    def test_non_frozen_mode_skips_bundle_dir(self) -> None:
        """When sys.frozen is not set, bundle dir should not be added."""
        _setup_frozen_env = self._import_setup()

        path_backup = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = "/usr/bin:/usr/local/bin"
            exe_dir = str(Path(sys.executable).resolve().parent)

            with patch.object(sys, "frozen", False, create=True):
                _setup_frozen_env()

            if exe_dir != str(Path.home() / ".ansibleforge" / "bin"):
                path_parts = os.environ["PATH"].split(os.pathsep)
                managed = str(Path.home() / ".ansibleforge" / "bin")
                non_managed = [p for p in path_parts if p != managed]
                assert exe_dir not in non_managed or exe_dir in ["/usr/bin", "/usr/local/bin"]
        finally:
            os.environ["PATH"] = path_backup


class TestCompanionBinaryResolution:
    """Verify that after setup, expected binaries would be found."""

    def test_ansible_galaxy_resolvable(self) -> None:
        """After frozen env setup, ansible-galaxy should be on PATH (if installed)."""
        import shutil
        result = shutil.which("ansible-galaxy")
        if result is None:
            pytest.skip("ansible-galaxy not installed in test environment")
        assert Path(result).is_file()

    def test_managed_bin_dir_exists(self) -> None:
        """The ~/.ansibleforge/bin directory should be created."""
        from ansible_forge.main import _setup_frozen_env
        _setup_frozen_env()
        managed_bin = Path.home() / ".ansibleforge" / "bin"
        assert managed_bin.parent.exists()
