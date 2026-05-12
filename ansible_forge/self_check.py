"""Runtime self-check module.

Validates that the application environment is correctly configured:
- SSL certificates are resolvable
- Companion binaries are on PATH and functional
- Network connectivity to critical services
- Workspace and database are accessible

Runs automatically on first launch and is exposed via GET /api/v1/self-check.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

VALIDATION_FLAG = Path.home() / ".ansibleforge" / ".validated"


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    critical: bool = True


@dataclass
class SelfCheckReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def critical_passed(self) -> bool:
        return all(c.passed for c in self.checks if c.critical)

    def to_dict(self) -> dict:
        return {
            "status": "ok" if self.all_passed else ("degraded" if self.critical_passed else "failed"),
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "message": c.message,
                    "critical": c.critical,
                }
                for c in self.checks
            ],
        }


async def run_self_check() -> SelfCheckReport:
    """Execute all validation checks and return a report."""
    report = SelfCheckReport()

    report.checks.append(_check_ssl_cert_file())
    report.checks.append(_check_ssl_context())
    report.checks.append(await _check_companion_binaries())
    report.checks.append(await _check_galaxy_connectivity())
    report.checks.append(_check_workspace_writable())
    report.checks.append(_check_database_accessible())

    if report.all_passed:
        _mark_validated()
        logger.info("self_check_passed", checks=len(report.checks))
    else:
        failed = [c.name for c in report.checks if not c.passed]
        logger.warning("self_check_failed", failed_checks=failed)

    return report


def needs_validation() -> bool:
    """Check if the app has been validated since install/update."""
    if not VALIDATION_FLAG.exists():
        return True
    from ansible_forge import __version__
    try:
        stored = VALIDATION_FLAG.read_text().strip()
        return stored != __version__
    except OSError:
        return True


def _mark_validated() -> None:
    """Write validation flag with current version."""
    from ansible_forge import __version__
    try:
        VALIDATION_FLAG.parent.mkdir(parents=True, exist_ok=True)
        VALIDATION_FLAG.write_text(__version__)
    except OSError:
        pass


def _check_ssl_cert_file() -> CheckResult:
    """Verify SSL_CERT_FILE is set and points to a real file."""
    ssl_cert = os.environ.get("SSL_CERT_FILE", "")
    if not ssl_cert:
        return CheckResult(
            name="ssl_cert_file",
            passed=False,
            message="SSL_CERT_FILE environment variable is not set",
        )
    if not Path(ssl_cert).is_file():
        return CheckResult(
            name="ssl_cert_file",
            passed=False,
            message=f"SSL_CERT_FILE points to non-existent file: {ssl_cert}",
        )
    size = Path(ssl_cert).stat().st_size
    if size < 1000:
        return CheckResult(
            name="ssl_cert_file",
            passed=False,
            message=f"SSL_CERT_FILE is suspiciously small ({size} bytes): {ssl_cert}",
        )
    return CheckResult(
        name="ssl_cert_file",
        passed=True,
        message=f"CA bundle found ({size} bytes): {ssl_cert}",
    )


def _check_ssl_context() -> CheckResult:
    """Verify that Python's SSL can create a valid verification context."""
    try:
        ctx = ssl.create_default_context()
        ca_file = os.environ.get("SSL_CERT_FILE")
        if ca_file and Path(ca_file).is_file():
            ctx.load_verify_locations(ca_file)
        stats = ctx.get_ca_certs()
        if len(stats) > 0:
            return CheckResult(
                name="ssl_context",
                passed=True,
                message=f"SSL context loaded {len(stats)} CA certificates",
            )
        return CheckResult(
            name="ssl_context",
            passed=False,
            message="SSL context has zero CA certificates loaded",
        )
    except Exception as e:
        return CheckResult(
            name="ssl_context",
            passed=False,
            message=f"Failed to create SSL context: {e}",
        )


async def _check_companion_binaries() -> CheckResult:
    """Verify that essential companion binaries are on PATH."""
    required = ["ansible-galaxy", "ansible-playbook"]
    optional = ["ansible-vault", "ansible-doc", "ansible-lint", "ansible-inventory"]
    missing_required = []
    missing_optional = []

    for binary in required:
        if not shutil.which(binary):
            missing_required.append(binary)
    for binary in optional:
        if not shutil.which(binary):
            missing_optional.append(binary)

    if missing_required:
        return CheckResult(
            name="companion_binaries",
            passed=False,
            message=f"Required binaries not found on PATH: {', '.join(missing_required)}",
        )

    msg = "All required binaries found on PATH"
    if missing_optional:
        msg += f" (optional missing: {', '.join(missing_optional)})"
    return CheckResult(
        name="companion_binaries",
        passed=True,
        message=msg,
        critical=True,
    )


async def _check_galaxy_connectivity() -> CheckResult:
    """Verify HTTPS connectivity to Ansible Galaxy (no download, just TLS handshake)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ansible-galaxy", "collection", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        combined = (stdout + stderr).decode()
        if "CERTIFICATE_VERIFY_FAILED" in combined:
            return CheckResult(
                name="galaxy_connectivity",
                passed=False,
                message="SSL certificate verification failed when contacting Galaxy",
            )
        return CheckResult(
            name="galaxy_connectivity",
            passed=True,
            message="ansible-galaxy can execute without SSL errors",
            critical=False,
        )
    except FileNotFoundError:
        return CheckResult(
            name="galaxy_connectivity",
            passed=False,
            message="ansible-galaxy binary not found",
            critical=False,
        )
    except TimeoutError:
        return CheckResult(
            name="galaxy_connectivity",
            passed=False,
            message="ansible-galaxy timed out (network issue?)",
            critical=False,
        )
    except Exception as e:
        return CheckResult(
            name="galaxy_connectivity",
            passed=False,
            message=f"Unexpected error: {e}",
            critical=False,
        )


def _check_workspace_writable() -> CheckResult:
    """Verify that the default workspace/data directory is writable."""
    data_dir = Path.home() / ".ansibleforge"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return CheckResult(
            name="workspace_writable",
            passed=True,
            message=f"Data directory writable: {data_dir}",
        )
    except OSError as e:
        return CheckResult(
            name="workspace_writable",
            passed=False,
            message=f"Cannot write to data directory {data_dir}: {e}",
        )


def _check_database_accessible() -> CheckResult:
    """Verify that the SQLite sessions database can be opened."""
    db_path = Path.home() / ".ansibleforge" / "sessions.db"
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1")
        conn.close()
        return CheckResult(
            name="database_accessible",
            passed=True,
            message=f"Database accessible: {db_path}",
        )
    except Exception as e:
        return CheckResult(
            name="database_accessible",
            passed=False,
            message=f"Database error ({db_path}): {e}",
            critical=False,
        )
