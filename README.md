# AnsibleForge

The definitive AI agent harness for Ansible. Generate, validate, execute, and manage any Ansible workflow through natural language.

## Features

- **Natural Language to Ansible** — describe what you want; AnsibleForge generates playbooks, roles, and inventory
- **Multi-LLM Support** — OpenAI, Anthropic, Ollama, and 100+ providers via LiteLLM
- **Safety First** — every execution runs in `--check --diff` mode first, with human approval gates
- **10 Specialized Tools** — playbook generation, role scaffolding, inventory management, vault encryption, linting, Molecule testing, Galaxy collections, execution, facts collection, and module doc search
- **Rollback Planning** — automatic rollback playbooks for destructive operations
- **Pre-execution Validation** — catches dangerous patterns (rm -rf, privilege escalation, unencrypted secrets) before they run
- **API-First** — clean REST API with SSE streaming, ready for any frontend
- **Web UI** — rich, power-user dashboard with real-time streaming, YAML editor, diff viewer, and one-click approval

## Quick Start

```bash
# Install with uv
uv pip install -e ".[all]"

# Or with pip
pip install -e ".[all]"

# Configure (copy and edit)
cp .env.example .env

# Run the server
ansible-forge
# or
uvicorn ansible_forge.main:app --host 0.0.0.0 --port 8420
```

## API Usage

### Chat (Natural Language)

```bash
curl -X POST http://localhost:8420/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Install and configure nginx on my Ubuntu servers"}'
```

### Direct Execution

```bash
curl -X POST http://localhost:8420/api/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "playbook_content": "---\n- name: Test\n  hosts: localhost\n  tasks:\n    - ansible.builtin.debug:\n        msg: Hello",
    "mode": "check"
  }'
```

### Lint a Playbook

```bash
curl -X POST http://localhost:8420/api/v1/lint \
  -H "Content-Type: application/json" \
  -d '{"content": "---\n- name: Test\n  hosts: all\n  tasks: []", "profile": "moderate"}'
```

### Health Check

```bash
curl http://localhost:8420/api/v1/health
```

## Configuration

All settings via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANSIBLEFORGE_LLM_PROVIDER` | `anthropic` | LLM provider (openai/anthropic/ollama) |
| `ANSIBLEFORGE_LLM_MODEL` | `anthropic/claude-sonnet-4-20250514` | Default model |
| `ANSIBLEFORGE_LLM_FALLBACK_MODELS` | `[]` | Comma-separated fallback model chain |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `ANSIBLEFORGE_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `ANSIBLEFORGE_MAX_AGENT_STEPS` | `15` | Max ReAct loop iterations |
| `ANSIBLEFORGE_API_KEY` | — | API key for authentication (blank = disabled) |
| `ANSIBLEFORGE_PORT` | `8420` | Server port |

## Architecture

```
AnsibleForge
├── API Layer (FastAPI + SSE)
├── Agent Core (ReAct Loop + Memory)
│   ├── LLM Client (LiteLLM multi-provider)
│   └── Tool Router
├── Tool Suite (10 tools)
│   ├── PlaybookGenerator, RoleScaffolder
│   ├── InventoryManager, VaultManager
│   ├── LintRunner, MoleculeRunner, DocSearcher
│   └── Executor, FactsCollector, GalaxyManager
├── Safety Layer
│   ├── Dry-Run (check+diff)
│   ├── Diff Analyzer
│   ├── Approval Gate
│   ├── Rollback Planner
│   └── Validators
└── Workspace Manager (session-isolated)
```

## Web UI

AnsibleForge includes a rich operations dashboard built with React, TypeScript, and Tailwind CSS.

```bash
# Development (hot-reload, proxies API to :8420)
cd ui && npm install && npm run dev

# Production build (served automatically by FastAPI)
cd ui && npm run build
```

After building, the UI is served at `http://localhost:8420/` alongside the API.

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check ansible_forge/ tests/

# Type check
mypy ansible_forge/
```

## License

MIT
