"""Execute Terraform commands — init, plan, apply, destroy, import, output, state."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools._log_tailer import snapshot_log_files, tail_new_logs
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus
from ansible_forge.tools.binary_resolver import resolve_terraform_or_download_async

logger = get_logger(__name__)

_MAX_TF_TIMEOUT = 86400

_DEFAULT_TF_TIMEOUTS: dict[str, int] = {
    "init": 120,
    "validate": 120,
    "fmt": 120,
    "plan": 600,
    "apply": 1800,
    "destroy": 1800,
    "import": 120,
    "output": 60,
    "state": 60,
    "workspace": 60,
}


def _effective_timeout(action: str, user_timeout: int) -> int:
    default = _DEFAULT_TF_TIMEOUTS.get(action, 600)
    if user_timeout and user_timeout > 0:
        return min(user_timeout, _MAX_TF_TIMEOUT)
    return default


_PROVIDER_ENV_VARS: dict[str, list[str]] = {
    "aws": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"],
    "azure": ["ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID"],
    "gcp": ["GOOGLE_CREDENTIALS", "GOOGLE_PROJECT", "GOOGLE_REGION"],
    "digitalocean": ["DIGITALOCEAN_TOKEN", "DO_API_TOKEN"],
    "hetzner": ["HCLOUD_TOKEN"],
}


class TerraformExecutor(BaseTool):
    @property
    def name(self) -> str:
        return "terraform_exec"

    @property
    def description(self) -> str:
        return (
            "Execute Terraform commands in the workspace. Supports: init (download providers), "
            "plan (preview changes), apply (create/modify infrastructure, requires approval), "
            "destroy (tear down infrastructure, requires approval), import (adopt existing "
            "resources into state), output (read outputs for Ansible handoff), state (inspect "
            "current state), validate (check syntax), and fmt (format HCL files). Cloud "
            "credentials are injected from the SecretVault automatically — the user provides "
            "them via request_secret."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "action": {
                    "type": "string",
                    "enum": ["init", "plan", "apply", "destroy", "import", "output", "state", "state_mv", "state_rm", "validate", "fmt", "workspace"],
                    "description": "Terraform action to execute",
                },
                "var_file": {
                    "type": "string",
                    "description": "Path to a .tfvars file relative to workspace/terraform/ (optional)",
                },
                "variables": {
                    "type": "object",
                    "description": "Terraform variables to pass via -var flags (key=value pairs)",
                    "additionalProperties": {},
                },
                "target": {
                    "type": "string",
                    "description": "Target specific resource for plan/apply/destroy (e.g. 'aws_instance.web')",
                },
                "import_address": {
                    "type": "string",
                    "description": "Terraform resource address for import (e.g. 'aws_instance.web')",
                },
                "import_id": {
                    "type": "string",
                    "description": "Cloud resource ID to import (e.g. 'i-0abc123def456')",
                },
                "auto_approve": {
                    "type": "boolean",
                    "description": "Skip interactive approval for apply/destroy (default: false — uses approval gate)",
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Workspace name for workspace action (select/new/delete). Omit for list.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Max seconds to wait. Defaults: init/validate/fmt=120, plan=600, "
                        "apply/destroy=1800, import=120. Set higher for large infrastructure "
                        "(e.g. EKS/RDS creation can take 30+ min). Max: 86400 (24 hours)."
                    ),
                    "minimum": 60,
                    "maximum": 86400,
                },
            },
            "required": ["workspace_path", "action"],
        }

    async def _find_terraform(self) -> str | None:
        from ansible_forge.tools.ee_runtime import is_ee_enabled

        if is_ee_enabled():
            return "tofu"
        try:
            return await resolve_terraform_or_download_async()
        except Exception as exc:
            logger.warning("terraform_resolve_failed", error=str(exc))
            return None

    def _build_secret_env(self, session_id: str) -> dict[str, str]:
        env = os.environ.copy()
        if not session_id:
            return env
        vault = SecretVault.get_instance().for_session(session_id)
        for name, value in vault.get_all().items():
            if name.isupper() or name.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                env[name] = str(value)
        return env

    _PEM_MARKERS = ("-----BEGIN", "-----BEGIN RSA", "-----BEGIN OPENSSH", "-----BEGIN EC")
    _KEY_HINT_NAMES = ("private_key", "ssh_key", "pem", "tls_key", "key_pem")

    @staticmethod
    def _extract_keys_to_vault(
        outputs: dict[str, Any], session_id: str,
    ) -> int:
        """Auto-store PEM-formatted keys from terraform outputs into the vault.

        Returns the count of keys stored.
        """
        vault = SecretVault.get_instance().for_session(session_id)
        stored = 0
        for name, value in outputs.items():
            if not isinstance(value, str):
                continue
            val = value.strip()
            is_pem = any(val.startswith(m) for m in TerraformExecutor._PEM_MARKERS)
            name_hint = any(h in name.lower() for h in TerraformExecutor._KEY_HINT_NAMES)
            if not (is_pem or name_hint):
                continue
            if not val:
                continue
            vault_name = name.upper() if name == name.lower() else name
            vault.store(vault_name, val, description=f"Auto-extracted from terraform output '{name}'")
            stored += 1
            logger.info("tf_key_auto_stored", output_name=name, vault_name=vault_name)
        return stored

    async def _run_terraform(
        self,
        tf_binary: str,
        tf_dir: Path,
        args: list[str],
        env: dict[str, str],
        timeout: int = 600,
        live_queue: asyncio.Queue | None = None,
    ) -> tuple[int, str, str]:
        from ansible_forge.tools.ee_runtime import ee_exec, is_ee_enabled

        if is_ee_enabled():
            ee_binary = "tofu" if "tofu" in tf_binary else "terraform"
            return await ee_exec(
                [ee_binary, *args], cwd=tf_dir, env=env, timeout=timeout, ws=tf_dir,
            )

        cmd = [tf_binary] + args
        proc = None
        log_watcher: asyncio.Task[None] | None = None
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        try:
            log_snapshot = snapshot_log_files(tf_dir) if live_queue else {}

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(tf_dir),
                env=env,
            )

            if live_queue and tf_dir.is_dir():
                log_watcher = asyncio.create_task(
                    tail_new_logs(tf_dir, log_snapshot, live_queue)
                )

            async def _read_stream(
                stream: asyncio.StreamReader, parts: list[str], is_stderr: bool = False,
            ) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    parts.append(decoded)
                    if live_queue is not None and decoded.strip():
                        with contextlib.suppress(Exception):
                            live_queue.put_nowait({
                                "type": "stderr_line" if is_stderr else "shell_output",
                                "line": decoded[:500],
                            })

            assert proc.stdout is not None
            assert proc.stderr is not None
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, stdout_parts),
                    _read_stream(proc.stderr, stderr_parts, is_stderr=True),
                    proc.wait(),
                ),
                timeout=timeout + 10,
            )
            rc = proc.returncode or 0
            return rc, "\n".join(stdout_parts), "\n".join(stderr_parts)
        except asyncio.CancelledError:
            if proc is not None:
                proc.kill()
                await proc.wait()
            logger.info("terraform_cancelled", args=args[:3])
            raise
        except (TimeoutError, subprocess.TimeoutExpired):
            if proc is not None:
                proc.kill()
                await proc.wait()
            return 1, "", f"Terraform command timed out after {timeout}s"
        finally:
            if log_watcher is not None and not log_watcher.done():
                log_watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await log_watcher

    async def execute(
        self,
        workspace_path: str = "",
        action: str = "",
        var_file: str = "",
        variables: dict[str, Any] | None = None,
        target: str = "",
        import_address: str = "",
        import_id: str = "",
        auto_approve: bool = False,
        timeout: int = 0,
        workspace_name: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not action:
            return ToolResult.fail("workspace_path and action are required")

        tf_binary = await self._find_terraform()
        if not tf_binary:
            return ToolResult.fail(
                "Terraform (or OpenTofu) could not be found or downloaded. "
                "Check your network connection or install manually: "
                "https://opentofu.org/docs/intro/install/"
            )

        tf_dir = Path(workspace_path) / "terraform"
        if not tf_dir.exists():
            if action == "init":
                tf_dir.mkdir(parents=True, exist_ok=True)
            else:
                return ToolResult.fail(
                    "No terraform/ directory in workspace. Run generate_terraform first."
                )

        session_id = kwargs.get("_session_id", "")
        env = self._build_secret_env(session_id)
        env["TF_IN_AUTOMATION"] = "1"
        env["TF_INPUT"] = "0"

        live_queue: asyncio.Queue | None = kwargs.get("_live_log_queue")

        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return ToolResult.fail(f"Unknown action: {action}")

        result = await handler(
            tf_binary, tf_dir, env,
            var_file=var_file,
            variables=variables,
            target=target,
            import_address=import_address,
            import_id=import_id,
            auto_approve=auto_approve,
            timeout=timeout,
            workspace_name=workspace_name,
            _live_queue=live_queue,
        )

        if action in ("output", "apply") and session_id and result.data.get("outputs"):
            self._extract_keys_to_vault(result.data["outputs"], session_id)

        return result

    async def _do_init(self, tf: str, tf_dir: Path, env: dict, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any) -> ToolResult:
        rc, out, err = await self._run_terraform(tf, tf_dir, ["init", "-no-color"], env, timeout=_effective_timeout("init", timeout), live_queue=_live_queue)
        if rc != 0:
            return ToolResult.fail(f"terraform init failed:\n{err.strip() or out.strip()}")
        return ToolResult.ok(
            output="Infrastructure tool initialized. Required cloud providers are ready.",
            stdout=out[-3000:],
        )

    async def _do_validate(self, tf: str, tf_dir: Path, env: dict, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any) -> ToolResult:
        rc, out, err = await self._run_terraform(tf, tf_dir, ["validate", "-no-color", "-json"], env, timeout=_effective_timeout("validate", timeout), live_queue=_live_queue)
        if rc != 0:
            return ToolResult.fail(f"Terraform validation failed:\n{out.strip() or err.strip()}")
        try:
            result = json.loads(out)
            if result.get("valid"):
                return ToolResult.ok(output="Terraform configuration is valid.")
            diagnostics = result.get("diagnostics", [])
            errors = [d.get("summary", "") for d in diagnostics if d.get("severity") == "error"]
            return ToolResult.fail(f"Validation errors: {'; '.join(errors)}")
        except json.JSONDecodeError:
            return ToolResult.ok(output=out.strip())

    async def _do_fmt(self, tf: str, tf_dir: Path, env: dict, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any) -> ToolResult:
        rc, out, err = await self._run_terraform(tf, tf_dir, ["fmt", "-no-color", "-diff"], env, timeout=_effective_timeout("fmt", timeout), live_queue=_live_queue)
        if rc != 0:
            return ToolResult.fail(f"terraform fmt failed: {err}")
        return ToolResult.ok(
            output="Terraform files formatted." if not out.strip() else f"Formatted:\n{out[:2000]}",
        )

    async def _do_import(
        self, tf: str, tf_dir: Path, env: dict,
        import_address: str = "", import_id: str = "", timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        if not import_address or not import_id:
            return ToolResult.fail(
                "import requires both import_address (e.g. 'aws_instance.web') "
                "and import_id (e.g. 'i-0abc123def456')."
            )
        rc, out, err = await self._run_terraform(
            tf, tf_dir,
            ["import", "-no-color", "-input=false", import_address, import_id],
            env, timeout=_effective_timeout("import", timeout), live_queue=_live_queue,
        )
        if rc != 0:
            return ToolResult.fail(
                f"terraform import failed:\n{(err.strip() or out.strip())[-3000:]}"
            )
        return ToolResult.ok(
            output=f"Resource '{import_address}' imported as '{import_id}'. "
            f"Run terraform plan to verify the configuration matches.",
            stdout=out[-3000:],
        )

    async def _do_plan(
        self, tf: str, tf_dir: Path, env: dict,
        var_file: str = "", variables: dict | None = None, target: str = "", timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        args = ["plan", "-no-color", "-input=false"]
        if var_file:
            args.extend(["-var-file", var_file])
        if variables:
            for k, v in variables.items():
                args.extend(["-var", f"{k}={v}"])
        if target:
            args.extend(["-target", target])

        rc, out, err = await self._run_terraform(tf, tf_dir, args, env, timeout=_effective_timeout("plan", timeout), live_queue=_live_queue)
        combined = out + "\n" + err

        if rc != 0:
            return ToolResult.fail(
                f"terraform plan failed:\n{combined.strip()[-3000:]}",
                raw_output=combined[-5000:],
            )

        add = combined.count(" will be created")
        change = combined.count(" will be updated")
        destroy = combined.count(" will be destroyed")
        no_changes = "No changes" in combined or "no changes" in combined.lower()

        summary = (
            "No changes needed — infrastructure matches configuration."
            if no_changes
            else f"Plan: {add} to add, {change} to change, {destroy} to destroy."
        )

        return ToolResult.ok(
            output=summary,
            plan_output=out[-8000:],
            additions=add,
            changes=change,
            destructions=destroy,
            no_changes=no_changes,
        )

    async def _do_apply(
        self, tf: str, tf_dir: Path, env: dict,
        var_file: str = "", variables: dict | None = None, target: str = "",
        auto_approve: bool = False, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        if not auto_approve:
            return ToolResult(
                status=ToolStatus.NEEDS_APPROVAL,
                output=(
                    "Terraform apply requires approval. This will create/modify real "
                    "cloud infrastructure and may incur costs. Review the plan output above."
                ),
                data={"action": "terraform_apply", "workspace": str(tf_dir)},
            )

        args = ["apply", "-no-color", "-input=false", "-auto-approve"]
        if var_file:
            args.extend(["-var-file", var_file])
        if variables:
            for k, v in variables.items():
                args.extend(["-var", f"{k}={v}"])
        if target:
            args.extend(["-target", target])

        rc, out, err = await self._run_terraform(tf, tf_dir, args, env, timeout=_effective_timeout("apply", timeout), live_queue=_live_queue)
        combined = out + "\n" + err

        if rc != 0:
            return ToolResult.fail(
                f"terraform apply failed:\n{combined.strip()[-3000:]}",
                raw_output=combined[-5000:],
            )

        added = combined.count(" created")
        changed = combined.count(" modified")
        destroyed = combined.count(" destroyed")

        return ToolResult.ok(
            output=f"Infrastructure changes applied: {added} created, {changed} modified, {destroyed} destroyed.",
            apply_output=out[-5000:],
            resources_created=added,
            resources_modified=changed,
            resources_destroyed=destroyed,
        )

    async def _do_destroy(
        self, tf: str, tf_dir: Path, env: dict,
        var_file: str = "", variables: dict | None = None, target: str = "",
        auto_approve: bool = False, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        if not auto_approve:
            return ToolResult(
                status=ToolStatus.NEEDS_APPROVAL,
                output=(
                    "Terraform DESTROY requires approval. This will PERMANENTLY DELETE "
                    "cloud infrastructure. This action cannot be undone."
                ),
                data={"action": "terraform_destroy", "workspace": str(tf_dir)},
            )

        args = ["destroy", "-no-color", "-input=false", "-auto-approve"]
        if var_file:
            args.extend(["-var-file", var_file])
        if variables:
            for k, v in variables.items():
                args.extend(["-var", f"{k}={v}"])
        if target:
            args.extend(["-target", target])

        rc, out, err = await self._run_terraform(tf, tf_dir, args, env, timeout=_effective_timeout("destroy", timeout), live_queue=_live_queue)
        if rc != 0:
            return ToolResult.fail(f"terraform destroy failed:\n{(out + err).strip()[-3000:]}")

        destroyed = (out + err).count(" destroyed")
        return ToolResult.ok(
            output=f"Infrastructure teardown complete: {destroyed} resource(s) destroyed.",
            destroy_output=out[-3000:],
        )

    async def _do_output(self, tf: str, tf_dir: Path, env: dict, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any) -> ToolResult:
        rc, out, err = await self._run_terraform(tf, tf_dir, ["output", "-no-color", "-json"], env, timeout=_effective_timeout("output", timeout))
        if rc != 0:
            return ToolResult.fail(f"terraform output failed: {err}")

        try:
            outputs = json.loads(out)
            flat: dict[str, Any] = {}
            for key, val in outputs.items():
                flat[key] = val.get("value") if isinstance(val, dict) else val

            return ToolResult.ok(
                output=f"Retrieved {len(flat)} infrastructure output(s) (IPs, endpoints, etc.).",
                outputs=flat,
                raw_outputs=outputs,
            )
        except json.JSONDecodeError:
            return ToolResult.ok(output=out.strip(), raw=out)

    async def _do_state(self, tf: str, tf_dir: Path, env: dict, timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any) -> ToolResult:
        rc, out, err = await self._run_terraform(tf, tf_dir, ["state", "list", "-no-color"], env, timeout=_effective_timeout("state", timeout))
        if rc != 0:
            if "No state file" in err or "no state" in err.lower():
                return ToolResult.ok(output="No infrastructure has been created yet. Run a plan and apply first.", resources=[])
            return ToolResult.fail(f"terraform state list failed: {err}")

        resources = [line.strip() for line in out.strip().splitlines() if line.strip()]

        rc2, show_out, _ = await self._run_terraform(
            tf, tf_dir, ["show", "-no-color", "-json"], env, timeout=60,
        )
        resource_details: dict[str, Any] = {}
        if rc2 == 0:
            try:
                state_data = json.loads(show_out)
                for res in (state_data.get("values", {}).get("root_module", {}).get("resources", [])):
                    addr = f"{res.get('type', '')}.{res.get('name', '')}"
                    resource_details[addr] = {
                        "type": res.get("type", ""),
                        "provider": res.get("provider_name", ""),
                        "values": {
                            k: v for k, v in (res.get("values", {}) or {}).items()
                            if k in ("id", "arn", "name", "public_ip", "private_ip",
                                     "public_dns", "status", "region", "tags", "size",
                                     "instance_type", "image", "location")
                        },
                    }
            except json.JSONDecodeError:
                logger.debug("tf_state_json_decode_failed", exc_info=True)

        return ToolResult.ok(
            output=f"Infrastructure state: {len(resources)} resource(s) currently managed.",
            resources=resources,
            resource_details=resource_details,
        )

    async def _do_state_mv(
        self, tf: str, tf_dir: Path, env: dict,
        variables: dict | None = None, timeout: int = 0,
        _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        if not variables or "source" not in variables or "destination" not in variables:
            return ToolResult.fail(
                "state_mv requires 'source' and 'destination' in variables. "
                "Example: variables={source: 'aws_instance.old', destination: 'aws_instance.new'}"
            )
        src = variables["source"]
        dst = variables["destination"]
        return ToolResult(
            status=ToolStatus.NEEDS_APPROVAL,
            output=f"Terraform state mv: rename '{src}' → '{dst}' in state. This modifies the state file.",
            data={"action": "state_mv", "source": src, "destination": dst, "risk_level": "high"},
        )

    async def _do_state_rm(
        self, tf: str, tf_dir: Path, env: dict,
        variables: dict | None = None, timeout: int = 0,
        _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        if not variables or "address" not in variables:
            return ToolResult.fail(
                "state_rm requires 'address' in variables. "
                "Example: variables={address: 'aws_instance.example'}"
            )
        addr = variables["address"]
        return ToolResult(
            status=ToolStatus.NEEDS_APPROVAL,
            output=f"Terraform state rm: remove '{addr}' from state. The real resource will NOT be destroyed but Terraform will no longer manage it.",
            data={"action": "state_rm", "address": addr, "risk_level": "high"},
        )

    async def _do_workspace(
        self, tf: str, tf_dir: Path, env: dict,
        workspace_name: str = "", timeout: int = 0, _live_queue: asyncio.Queue | None = None, **_: Any,
    ) -> ToolResult:
        t = _effective_timeout("workspace", timeout)
        if not workspace_name:
            rc, out, err = await self._run_terraform(
                tf, tf_dir, ["workspace", "list", "-no-color"], env, timeout=t,
            )
            if rc != 0:
                return ToolResult.fail(f"terraform workspace list failed: {err}")
            workspaces = [w.strip().lstrip("* ") for w in out.strip().splitlines() if w.strip()]
            current = next((w.strip().lstrip("* ") for w in out.strip().splitlines() if w.strip().startswith("*")), "default")
            return ToolResult.ok(
                output=f"{len(workspaces)} workspace(s) available, current: {current}",
                workspaces=workspaces,
                current=current,
            )

        rc, out, err = await self._run_terraform(
            tf, tf_dir, ["workspace", "select", "-no-color", workspace_name], env, timeout=t,
        )
        if rc == 0:
            return ToolResult.ok(output=f"Switched to workspace '{workspace_name}'.")

        rc, out, err = await self._run_terraform(
            tf, tf_dir, ["workspace", "new", "-no-color", workspace_name], env, timeout=t,
        )
        if rc != 0:
            return ToolResult.fail(f"Failed to select or create workspace '{workspace_name}': {err}")
        return ToolResult.ok(output=f"Created and switched to new workspace '{workspace_name}'.")
