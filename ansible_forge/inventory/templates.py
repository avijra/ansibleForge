"""Cloud inventory plugin templates for Ansible dynamic inventory."""

from __future__ import annotations

from typing import Any

_TEMPLATES: dict[str, dict[str, Any]] = {
    "amazon.aws.aws_ec2": {
        "plugin_type": "amazon.aws.aws_ec2",
        "name": "AWS EC2",
        "description": "Discover EC2 instances from AWS. Groups hosts by tags, instance type, and region.",
        "required_collections": ["amazon.aws"],
        "required_env_vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        "optional_env_vars": ["AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"],
        "default_config": (
            "plugin: amazon.aws.aws_ec2\n"
            "regions:\n"
            "  - us-east-1\n"
            "filters:\n"
            "  instance-state-name:\n"
            "    - running\n"
            "keyed_groups:\n"
            "  - key: tags.Name\n"
            "    prefix: name\n"
            "    separator: _\n"
            "  - key: instance_type\n"
            "    prefix: type\n"
            "  - key: placement.region\n"
            "    prefix: region\n"
            "hostnames:\n"
            "  - private-ip-address\n"
            "compose:\n"
            "  ansible_host: private_ip_address\n"
        ),
    },
    "azure.azcollection.azure_rm": {
        "plugin_type": "azure.azcollection.azure_rm",
        "name": "Azure VMs",
        "description": "Discover Azure virtual machines. Groups hosts by resource group, location, and tags.",
        "required_collections": ["azure.azcollection"],
        "required_env_vars": ["AZURE_SUBSCRIPTION_ID", "AZURE_CLIENT_ID", "AZURE_SECRET", "AZURE_TENANT"],
        "optional_env_vars": [],
        "default_config": (
            "plugin: azure.azcollection.azure_rm\n"
            "include_vm_resource_groups:\n"
            "  - '*'\n"
            "auth_source: env\n"
            "keyed_groups:\n"
            "  - key: resource_group\n"
            "    prefix: rg\n"
            "    separator: _\n"
            "  - key: location\n"
            "    prefix: loc\n"
            "  - key: tags.environment | default('untagged')\n"
            "    prefix: env\n"
            "hostnames:\n"
            "  - default\n"
            "compose:\n"
            "  ansible_host: private_ipv4_addresses[0] | default(public_ip_address, true)\n"
        ),
    },
    "google.cloud.gcp_compute": {
        "plugin_type": "google.cloud.gcp_compute",
        "name": "GCP Compute",
        "description": "Discover GCP Compute Engine instances. Groups hosts by zone, labels, and machine type.",
        "required_collections": ["google.cloud"],
        "required_env_vars": ["GCP_SERVICE_ACCOUNT_FILE"],
        "optional_env_vars": ["GCP_PROJECT"],
        "default_config": (
            "plugin: google.cloud.gcp_compute\n"
            "projects:\n"
            "  - my-project\n"
            "zones: []\n"
            "filters:\n"
            "  - status = RUNNING\n"
            "keyed_groups:\n"
            "  - key: zone\n"
            "    prefix: zone\n"
            "  - key: labels.environment | default('untagged')\n"
            "    prefix: env\n"
            "  - key: machine_type\n"
            "    prefix: type\n"
            "hostnames:\n"
            "  - name\n"
            "compose:\n"
            "  ansible_host: networkInterfaces[0].networkIP\n"
        ),
    },
    "community.digitalocean.digitalocean": {
        "plugin_type": "community.digitalocean.digitalocean",
        "name": "DigitalOcean",
        "description": "Discover DigitalOcean droplets. Groups hosts by region, size, and tags.",
        "required_collections": ["community.digitalocean"],
        "required_env_vars": ["DO_API_TOKEN"],
        "optional_env_vars": [],
        "default_config": (
            "plugin: community.digitalocean.digitalocean\n"
            "attributes:\n"
            "  - id\n"
            "  - name\n"
            "  - memory\n"
            "  - vcpus\n"
            "  - disk\n"
            "  - image\n"
            "  - ip_address\n"
            "  - status\n"
            "  - tags\n"
            "  - region\n"
            "keyed_groups:\n"
            "  - key: do_region.slug\n"
            "    prefix: region\n"
            "  - key: do_tags | default([])\n"
            "    prefix: tag\n"
            "  - key: do_size.slug\n"
            "    prefix: size\n"
            "compose:\n"
            "  ansible_host: do_networks.v4 | selectattr('type','eq','public') | map(attribute='ip_address') | first\n"
        ),
    },
    "hetzner.hcloud.hcloud": {
        "plugin_type": "hetzner.hcloud.hcloud",
        "name": "Hetzner Cloud",
        "description": "Discover Hetzner Cloud servers. Groups hosts by location, server type, and labels.",
        "required_collections": ["hetzner.hcloud"],
        "required_env_vars": ["HCLOUD_TOKEN"],
        "optional_env_vars": [],
        "default_config": (
            "plugin: hetzner.hcloud.hcloud\n"
            "keyed_groups:\n"
            "  - key: location\n"
            "    prefix: loc\n"
            "  - key: server_type\n"
            "    prefix: type\n"
            "  - key: labels.environment | default('untagged')\n"
            "    prefix: env\n"
            "compose:\n"
            "  ansible_host: ipv4_address\n"
        ),
    },
    "openstack.cloud.openstack": {
        "plugin_type": "openstack.cloud.openstack",
        "name": "OpenStack",
        "description": "Discover OpenStack instances. Groups hosts by project, availability zone, and metadata.",
        "required_collections": ["openstack.cloud"],
        "required_env_vars": ["OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME"],
        "optional_env_vars": ["OS_USER_DOMAIN_NAME", "OS_PROJECT_DOMAIN_NAME"],
        "default_config": (
            "plugin: openstack.cloud.openstack\n"
            "expand_hostvars: true\n"
            "fail_on_errors: true\n"
            "keyed_groups:\n"
            "  - key: openstack.availability_zone\n"
            "    prefix: az\n"
            "  - key: openstack.metadata.environment | default('untagged')\n"
            "    prefix: env\n"
            "compose:\n"
            "  ansible_host: openstack.accessIPv4 | default(openstack.private_v4)\n"
        ),
    },
    "generic": {
        "plugin_type": "generic",
        "name": "Custom Plugin",
        "description": "Use any Ansible inventory plugin by providing a raw YAML configuration.",
        "required_collections": [],
        "required_env_vars": [],
        "optional_env_vars": [],
        "default_config": (
            "plugin: <your_plugin_fqcn>\n"
        ),
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in t.items() if k != "default_config"}
        for t in _TEMPLATES.values()
    ]


def get_template(plugin_type: str) -> dict[str, Any] | None:
    return _TEMPLATES.get(plugin_type)
