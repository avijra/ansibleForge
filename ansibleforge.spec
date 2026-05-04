# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bundling the AnsibleForge backend into a standalone directory.

Builds the main backend executable plus frozen Ansible CLI tools
(ansible-playbook, ansible-galaxy, ansible-vault, ansible-doc, ansible-lint)
so the packaged app is fully self-contained — no system Python required.
"""

import importlib
import os
import sys
from pathlib import Path

block_cipher = None

project_root = os.path.abspath(".")
ui_dist = os.path.join(project_root, "ui", "dist")
cli_entries = os.path.join(project_root, "scripts", "cli_entries")

hidden_imports = [
    # --- Core framework ---
    "ansible_forge",
    "ansible_forge.main",
    "ansible_forge.config",
    "ansible_forge.logging",
    "ansible_forge.api.router",
    "ansible_forge.api.endpoints.chat",
    "ansible_forge.api.endpoints.collections",
    "ansible_forge.api.endpoints.execute",
    "ansible_forge.api.endpoints.health",
    "ansible_forge.api.endpoints.inventory",
    "ansible_forge.api.endpoints.knowledge",
    "ansible_forge.api.endpoints.lint",
    "ansible_forge.api.endpoints.playbooks",
    "ansible_forge.api.endpoints.secrets",
    "ansible_forge.api.endpoints.sessions",
    "ansible_forge.api.endpoints.settings",
    "ansible_forge.api.endpoints.terminal",
    "ansible_forge.api.endpoints.workspace_files",
    "ansible_forge.api.middleware.auth",
    "ansible_forge.api.middleware.logging",
    "ansible_forge.agent.orchestrator",
    "ansible_forge.agent.types",
    "ansible_forge.agent.llm_client",
    "ansible_forge.agent.memory",
    "ansible_forge.agent.planner",
    "ansible_forge.agent.prompts.system",
    "ansible_forge.agent.prompts.templates",
    "ansible_forge.knowledge.consolidation",
    "ansible_forge.knowledge.context",
    "ansible_forge.knowledge.experience_store",
    "ansible_forge.knowledge.extractor",
    "ansible_forge.knowledge.graph",
    "ansible_forge.knowledge.reflection",
    "ansible_forge.knowledge.schema",
    "ansible_forge.persistence.session_store",
    "ansible_forge.safety.approval",
    "ansible_forge.safety.diff_analyzer",
    "ansible_forge.safety.dry_run",
    "ansible_forge.safety.rollback",
    "ansible_forge.safety.secret_vault",
    "ansible_forge.safety.validators",
    "ansible_forge.tools.base",
    "ansible_forge.tools.connectivity_tester",
    "ansible_forge.tools.doc_searcher",
    "ansible_forge.tools.executor",
    "ansible_forge.tools.facts_collector",
    "ansible_forge.tools.file_writer",
    "ansible_forge.tools.galaxy_manager",
    "ansible_forge.tools.inventory_manager",
    "ansible_forge.tools.lint_runner",
    "ansible_forge.tools.molecule_runner",
    "ansible_forge.tools.playbook_generator",
    "ansible_forge.tools.registry",
    "ansible_forge.tools.role_scaffolder",
    "ansible_forge.tools.secret_requester",
    "ansible_forge.tools.vault_manager",
    "ansible_forge.tools.web_searcher",
    "ansible_forge.tools.adhoc_runner",
    "ansible_forge.tools.binary_resolver",
    "ansible_forge.tools.compliance_scanner",
    "ansible_forge.tools.config_comparator",
    "ansible_forge.tools.drift_detector",
    "ansible_forge.tools.git_manager",
    "ansible_forge.tools.inventory_discovery",
    "ansible_forge.tools.log_analyzer",
    "ansible_forge.tools.project_importer",
    "ansible_forge.tools.rollback_tool",
    "ansible_forge.tools.schedule_manager",
    "ansible_forge.tools.template_renderer",
    "ansible_forge.tools.terraform_executor",
    "ansible_forge.tools.terraform_generator",
    "ansible_forge.tools.terraform_inventory",
    "ansible_forge.tools.variable_inspector",
    "ansible_forge.tools.verifier",
    "ansible_forge.inventory",
    "ansible_forge.inventory.templates",
    "ansible_forge.persistence.infrastructure_store",
    "ansible_forge.workspace.manager",
    "ansible_forge.workspace.project_layout",
    # --- FastAPI / Starlette / Uvicorn ---
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.responses",
    "fastapi.staticfiles",
    "starlette",
    "starlette.middleware",
    "starlette.routing",
    "starlette.responses",
    "uvicorn",
    "uvicorn.config",
    "uvicorn.main",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "sse_starlette",
    "sse_starlette.sse",
    # --- Pydantic ---
    "pydantic",
    "pydantic.fields",
    "pydantic_settings",
    "pydantic_core",
    # --- LiteLLM (large; pull in core + common providers) ---
    "litellm",
    "litellm.main",
    "litellm.utils",
    "litellm.llms",
    "litellm.llms.anthropic",
    "litellm.llms.openai",
    # --- Ansible ---
    "ansible",
    "ansible.cli",
    "ansible.cli.playbook",
    "ansible.cli.galaxy",
    "ansible.cli.vault",
    "ansible.cli.doc",
    "ansible.cli.inventory",
    "ansible.config",
    "ansible.constants",
    "ansible.context",
    "ansible.executor",
    "ansible.executor.task_queue_manager",
    "ansible.executor.playbook_executor",
    "ansible.galaxy",
    "ansible.inventory",
    "ansible.module_utils",
    "ansible.modules",
    "ansible.parsing",
    "ansible.playbook",
    "ansible.plugins",
    "ansible.plugins.callback",
    "ansible.plugins.connection",
    "ansible.plugins.shell",
    "ansible.plugins.become",
    "ansible.plugins.strategy",
    "ansible.plugins.strategy.linear",
    "ansible.plugins.strategy.free",
    "ansible.plugins.action",
    "ansible.plugins.lookup",
    "ansible.plugins.filter",
    "ansible.plugins.test",
    "ansible.plugins.inventory",
    "ansible.vars.hostvars",
    "ansible.template",
    "ansible.utils",
    "ansible.vars",
    "ansible_runner",
    "ansible_runner.runner",
    "ansible_runner.config",
    "ansible_runner.config._ansible_runner",
    # --- ansible-lint ---
    "ansiblelint",
    "ansiblelint.__main__",
    "ansiblelint.app",
    "ansiblelint.cli",
    "ansiblelint.config",
    "ansiblelint.constants",
    "ansiblelint.errors",
    "ansiblelint.file_utils",
    "ansiblelint.formatter",
    "ansiblelint.rules",
    "ansiblelint.runner",
    "ansiblelint.skip_utils",
    "ansiblelint.text",
    "ansiblelint.yaml_utils",
    # --- tiktoken (for litellm token counting) ---
    "tiktoken",
    "tiktoken.registry",
    "tiktoken.load",
    "tiktoken.core",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    # --- Misc deps ---
    "structlog",
    "httpx",
    "tenacity",
    "aiofiles",
    "yaml",
    "jinja2",
    "jinja2.ext",
    "h11",
    "anyio",
    "sniffio",
    "certifi",
    "httpcore",
    "idna",
    "charset_normalizer",
    "kuzu",
    "sqlite3",
    "email.mime.text",
    "email.mime.multipart",
    "json",
    "multiprocessing",
]

datas = []

if os.path.isdir(ui_dist):
    datas.append((ui_dist, os.path.join("ui", "dist")))

try:
    ansible_path = os.path.dirname(importlib.import_module("ansible").__file__)
    datas.append((ansible_path, "ansible"))
except Exception:
    pass

try:
    ansible_runner_path = os.path.dirname(importlib.import_module("ansible_runner").__file__)
    datas.append((ansible_runner_path, "ansible_runner"))
except Exception:
    pass

try:
    litellm_path = os.path.dirname(importlib.import_module("litellm").__file__)
    datas.append((litellm_path, "litellm"))
except Exception:
    pass

try:
    import certifi
    ca_bundle = certifi.where()
    datas.append((ca_bundle, os.path.join("certifi", "")))
except Exception:
    pass

try:
    import tiktoken_ext
    tiktoken_ext_path = os.path.dirname(tiktoken_ext.__file__)
    datas.append((tiktoken_ext_path, "tiktoken_ext"))
except Exception:
    pass

try:
    ansiblelint_path = os.path.dirname(importlib.import_module("ansiblelint").__file__)
    datas.append((ansiblelint_path, "ansiblelint"))
except Exception:
    pass

excludes = [
    "matplotlib",
    "scipy",
    "numpy",
    "pandas",
    "tkinter",
    "_tkinter",
    "PIL",
    "cv2",
    "torch",
    "tensorflow",
    "IPython",
    "notebook",
    "sphinx",
    "docutils",
    "pytest",
    "hypothesis",
]

# ---------------------------------------------------------------------------
# Main backend
# ---------------------------------------------------------------------------
a_main = Analysis(
    [os.path.join("ansible_forge", "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ---------------------------------------------------------------------------
# Ansible CLI companions — share the same hidden imports / data so they can
# resolve all ansible modules from the shared _internal directory.
# ---------------------------------------------------------------------------
cli_tools = {
    "ansible-playbook": os.path.join(cli_entries, "cli_ansible_playbook.py"),
    "ansible-galaxy": os.path.join(cli_entries, "cli_ansible_galaxy.py"),
    "ansible-vault": os.path.join(cli_entries, "cli_ansible_vault.py"),
    "ansible-doc": os.path.join(cli_entries, "cli_ansible_doc.py"),
    "ansible-lint": os.path.join(cli_entries, "cli_ansible_lint.py"),
    "ansible-inventory": os.path.join(cli_entries, "cli_ansible_inventory.py"),
}

cli_analyses = {}
for tool_name, entry_script in cli_tools.items():
    cli_analyses[tool_name] = Analysis(
        [entry_script],
        pathex=[project_root],
        binaries=[],
        datas=datas,
        hiddenimports=hidden_imports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=excludes,
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )

# ---------------------------------------------------------------------------
# Deduplicate across all Analysis objects
# ---------------------------------------------------------------------------
merge_args = [(a_main, "ansibleforge-backend", "ansibleforge-backend")]
for tool_name, analysis in cli_analyses.items():
    merge_args.append((analysis, tool_name, tool_name))

MERGE(*merge_args)

# ---------------------------------------------------------------------------
# Build PYZ + EXE for main backend
# ---------------------------------------------------------------------------
pyz_main = PYZ(a_main.pure, a_main.zipped_data, cipher=block_cipher)

exe_main = EXE(
    pyz_main,
    a_main.scripts,
    [],
    exclude_binaries=True,
    name="ansibleforge-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

# ---------------------------------------------------------------------------
# Build PYZ + EXE for each CLI tool
# ---------------------------------------------------------------------------
cli_exes = {}
cli_pyzs = {}
for tool_name, analysis in cli_analyses.items():
    cli_pyzs[tool_name] = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)
    cli_exes[tool_name] = EXE(
        cli_pyzs[tool_name],
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=tool_name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
        disable_windowed_traceback=False,
    )

# ---------------------------------------------------------------------------
# Collect everything into one directory — all executables share _internal
# ---------------------------------------------------------------------------
collect_args = [
    exe_main,
    a_main.binaries,
    a_main.zipfiles,
    a_main.datas,
]

for tool_name in cli_analyses:
    collect_args.extend([
        cli_exes[tool_name],
        cli_analyses[tool_name].binaries,
        cli_analyses[tool_name].zipfiles,
        cli_analyses[tool_name].datas,
    ])

coll = COLLECT(
    *collect_args,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ansibleforge-backend",
)
