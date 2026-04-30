# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bundling the AnsibleForge backend into a standalone directory."""

import importlib
import os
import sys
from pathlib import Path

block_cipher = None

project_root = os.path.abspath(".")
ui_dist = os.path.join(project_root, "ui", "dist")

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
    "ansible.config",
    "ansible.constants",
    "ansible.context",
    "ansible.executor",
    "ansible.galaxy",
    "ansible.inventory",
    "ansible.module_utils",
    "ansible.modules",
    "ansible.parsing",
    "ansible.playbook",
    "ansible.plugins",
    "ansible.vars.hostvars",
    "ansible.template",
    "ansible.utils",
    "ansible.vars",
    "ansible_runner",
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
    "sqlite3",
    "email.mime.text",
    "email.mime.multipart",
    "json",
    "multiprocessing",
]

datas = []

if os.path.isdir(ui_dist):
    datas.append((ui_dist, os.path.join("ui", "dist")))

# Collect ansible data files (config, module_utils, plugins)
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

# Collect litellm data (model cost maps, etc.)
try:
    litellm_path = os.path.dirname(importlib.import_module("litellm").__file__)
    datas.append((litellm_path, "litellm"))
except Exception:
    pass

# Collect certifi CA bundle
try:
    import certifi
    ca_bundle = certifi.where()
    datas.append((ca_bundle, os.path.join("certifi", "")))
except Exception:
    pass

# Collect tiktoken_ext (encoding constructors)
try:
    import tiktoken_ext
    tiktoken_ext_path = os.path.dirname(tiktoken_ext.__file__)
    datas.append((tiktoken_ext_path, "tiktoken_ext"))
except Exception:
    pass

a = Analysis(
    [os.path.join("ansible_forge", "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ansibleforge-backend",
)
