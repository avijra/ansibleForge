"""Generate Terraform HCL configuration files from user intent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

PROVIDER_BLOCKS: dict[str, str] = {
    "aws": """\
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}
""",
    "azure": """\
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}
""",
    "gcp": """\
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region
}

variable "gcp_project" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}
""",
    "digitalocean": """\
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}
""",
    "hetzner": """\
terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.0"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}
""",
}

BACKEND_TEMPLATES: dict[str, str] = {
    "s3": """\
terraform {{
  backend "s3" {{
    bucket         = "{bucket}"
    key            = "{key}"
    region         = "{region}"
    use_lockfile   = true
    encrypt        = true
  }}
}}
""",
    "gcs": """\
terraform {{
  backend "gcs" {{
    bucket = "{bucket}"
    prefix = "{key}"
  }}
}}
""",
    "azurerm": """\
terraform {{
  backend "azurerm" {{
    resource_group_name  = "{resource_group}"
    storage_account_name = "{storage_account}"
    container_name       = "{container}"
    key                  = "{key}"
  }}
}}
""",
}

ANSIBLE_OUTPUT_BLOCK = """\

# ── Outputs for Ansible handoff ──────────────────────────────────────
# These outputs are automatically read by Tuyere to generate inventory.
"""


class TerraformGenerator(BaseTool):
    @property
    def name(self) -> str:
        return "generate_terraform"

    @property
    def description(self) -> str:
        return (
            "Generate Terraform HCL configuration files (.tf) in the workspace. "
            "Can write provider configuration, resource definitions, variables, "
            "and outputs. Supports AWS, Azure, GCP, DigitalOcean, and Hetzner "
            "provider templates. Output blocks are used for automatic Ansible "
            "inventory handoff after terraform apply."
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
                "filename": {
                    "type": "string",
                    "description": (
                        "HCL filename to write (e.g. 'main.tf', 'variables.tf', 'outputs.tf'). "
                        "Written to workspace/terraform/ directory."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full HCL content to write to the file",
                },
                "provider": {
                    "type": "string",
                    "enum": ["aws", "azure", "gcp", "digitalocean", "hetzner"],
                    "description": (
                        "If provided, auto-generates provider.tf with the provider block. "
                        "Use this for the initial setup instead of writing provider config manually."
                    ),
                },
                "append_ansible_outputs": {
                    "type": "boolean",
                    "description": (
                        "If true, appends standard output blocks for Ansible handoff "
                        "(instance IPs, hostnames). Default: false"
                    ),
                },
                "backend": {
                    "type": "object",
                    "description": (
                        "Remote state backend configuration. Generates backend.tf. "
                        "Requires 'type' (s3, gcs, azurerm) and type-specific config "
                        "like bucket, key, region, etc."
                    ),
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["s3", "gcs", "azurerm"],
                        },
                    },
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["workspace_path"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        filename: str = "",
        content: str = "",
        provider: str = "",
        append_ansible_outputs: bool = False,
        backend: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path:
            return ToolResult.fail("workspace_path is required")

        if not filename and not provider and not backend:
            return ToolResult.fail("Provide filename+content, provider, or backend configuration")

        ws = Path(workspace_path)
        tf_dir = ws / "terraform"
        tf_dir.mkdir(parents=True, exist_ok=True)

        written_files: list[str] = []

        if provider:
            provider_block = PROVIDER_BLOCKS.get(provider)
            if not provider_block:
                return ToolResult.fail(
                    f"Unknown provider: {provider}. "
                    f"Available: {', '.join(PROVIDER_BLOCKS.keys())}"
                )
            provider_file = tf_dir / "provider.tf"
            provider_file.write_text(provider_block, encoding="utf-8")
            written_files.append("provider.tf")
            logger.info("terraform_provider_written", provider=provider)

        if backend:
            backend_type = backend.get("type", "")
            template = BACKEND_TEMPLATES.get(backend_type)
            if not template:
                return ToolResult.fail(
                    f"Unknown backend type: {backend_type}. "
                    f"Available: {', '.join(BACKEND_TEMPLATES.keys())}"
                )
            config = {k: v for k, v in backend.items() if k != "type"}
            config.setdefault("bucket", "my-terraform-state")
            config.setdefault("key", "terraform.tfstate")
            config.setdefault("region", "us-east-1")
            config.setdefault("resource_group", "terraform-state-rg")
            config.setdefault("storage_account", "tfstateaccount")
            config.setdefault("container", "tfstate")
            backend_file = tf_dir / "backend.tf"
            backend_file.write_text(template.format(**config), encoding="utf-8")
            written_files.append("backend.tf")
            logger.info("terraform_backend_written", backend_type=backend_type)

        if filename and content:
            target = (tf_dir / filename).resolve()
            if not str(target).startswith(str(tf_dir.resolve())):
                return ToolResult.fail(f"Path escapes terraform directory: {filename}")
            final_content = content
            if append_ansible_outputs:
                final_content += ANSIBLE_OUTPUT_BLOCK
            target.write_text(final_content, encoding="utf-8")
            written_files.append(filename)
            logger.info("terraform_file_written", filename=filename, size=len(final_content))

        if not written_files:
            return ToolResult.fail("No files written. Provide filename+content or provider.")

        tf_files = sorted(f.name for f in tf_dir.iterdir() if f.suffix == ".tf")

        return ToolResult.ok(
            output=f"Wrote {len(written_files)} Terraform file(s): {', '.join(written_files)}",
            written_files=written_files,
            terraform_dir=str(tf_dir),
            all_tf_files=tf_files,
        )
