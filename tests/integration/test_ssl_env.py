"""Integration tests for SSL certificate environment setup.

Verifies that _setup_ssl_certs finds valid CA bundles and that the
SSL_CERT_FILE environment variable propagates to child subprocesses,
preventing CERTIFICATE_VERIFY_FAILED errors in packaged builds.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


class TestSetupSslCerts:
    """Test the _setup_ssl_certs function from main.py."""

    def _import_setup_ssl_certs(self):
        from ansible_forge.main import _setup_ssl_certs
        return _setup_ssl_certs

    def test_finds_system_ca_bundle_non_frozen(self) -> None:
        """In non-frozen mode, system CA paths should be findable."""
        _setup_ssl_certs = self._import_setup_ssl_certs()
        env_backup = os.environ.pop("SSL_CERT_FILE", None)
        try:
            _setup_ssl_certs("/nonexistent/bundle/dir")
            ssl_cert = os.environ.get("SSL_CERT_FILE", "")
            assert ssl_cert, "SSL_CERT_FILE not set after _setup_ssl_certs"
            assert Path(ssl_cert).is_file(), f"SSL_CERT_FILE points to non-existent: {ssl_cert}"
        finally:
            if env_backup:
                os.environ["SSL_CERT_FILE"] = env_backup
            else:
                os.environ.pop("SSL_CERT_FILE", None)

    def test_finds_bundled_cert_in_frozen_layout(self, tmp_path) -> None:
        """Simulates a PyInstaller _internal layout."""
        _setup_ssl_certs = self._import_setup_ssl_certs()

        cert_dir = tmp_path / "_internal" / "certifi"
        cert_dir.mkdir(parents=True)
        cacert = cert_dir / "cacert.pem"
        cacert.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")

        env_backup = os.environ.pop("SSL_CERT_FILE", None)
        try:
            _setup_ssl_certs(str(tmp_path))
            assert os.environ.get("SSL_CERT_FILE") == str(cacert)
            assert os.environ.get("REQUESTS_CA_BUNDLE") == str(cacert)
        finally:
            if env_backup:
                os.environ["SSL_CERT_FILE"] = env_backup
            else:
                os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("REQUESTS_CA_BUNDLE", None)

    def test_ssl_cert_file_overrides_existing(self, tmp_path) -> None:
        """Unconditional assignment should override pre-existing values."""
        _setup_ssl_certs = self._import_setup_ssl_certs()

        cert_dir = tmp_path / "_internal" / "certifi"
        cert_dir.mkdir(parents=True)
        cacert = cert_dir / "cacert.pem"
        cacert.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")

        env_backup = os.environ.get("SSL_CERT_FILE")
        try:
            os.environ["SSL_CERT_FILE"] = "/bogus/old/path"
            _setup_ssl_certs(str(tmp_path))
            assert os.environ["SSL_CERT_FILE"] == str(cacert), (
                "Should override existing SSL_CERT_FILE"
            )
        finally:
            if env_backup:
                os.environ["SSL_CERT_FILE"] = env_backup
            else:
                os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("REQUESTS_CA_BUNDLE", None)


class TestSslPropagation:
    """Verify that SSL_CERT_FILE propagates to child processes."""

    @pytest.mark.asyncio
    async def test_env_inherited_by_subprocess(self) -> None:
        """Child processes must see SSL_CERT_FILE from parent."""
        test_value = "/tmp/test_ca_propagation.pem"
        env = os.environ.copy()
        env["SSL_CERT_FILE"] = test_value

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import os; print(os.environ.get('SSL_CERT_FILE', 'MISSING'))",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        assert stdout.decode().strip() == test_value

    @pytest.mark.asyncio
    async def test_ssl_context_respects_cert_file(self) -> None:
        """Python's ssl module should use SSL_CERT_FILE for verification."""
        ssl_cert = os.environ.get("SSL_CERT_FILE", "")
        if not ssl_cert or not Path(ssl_cert).is_file():
            for candidate in [
                "/etc/ssl/cert.pem",
                "/etc/ssl/certs/ca-certificates.crt",
            ]:
                if Path(candidate).is_file():
                    ssl_cert = candidate
                    break

        if not ssl_cert:
            pytest.skip("No CA bundle available for SSL test")

        ctx = ssl.create_default_context(cafile=ssl_cert)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
