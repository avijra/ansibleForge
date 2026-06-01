"""Topic-specific instruction expansions for progressive disclosure.

The core system prompt stays compact. Topic docs are injected ONLY when
the user's message or context mentions relevant keywords.
"""

from __future__ import annotations

from typing import NamedTuple


class TopicDoc(NamedTuple):
    name: str
    keywords: frozenset[str]
    content: str


TOPIC_TERRAFORM = TopicDoc(
    name="terraform",
    keywords=frozenset({
        "terraform", "hcl", "tf", "provider", "tfvars", "state_mv",
        "state_rm", "backend", "module", "terraform_exec", "generate_terraform",
    }),
    content="""\
**TERRAFORM — Infrastructure Provisioning:** \
Use Terraform for creating/destroying cloud INFRASTRUCTURE (VPCs, instances, LBs, DNS). \
Use Ansible for configuring what runs ON servers. Use both for full-stack deployments. \
Terraform workflow is STRICT — follow this exact sequence: \
1. Collect cloud creds via `request_secret` \
2. Pre-flight resource limits \
3. Generate HCL files via `generate_terraform` \
4. `terraform_exec action=init` \
5. `terraform_exec action=plan` — MANDATORY before apply \
6. User reviews plan output → approval \
7. `terraform_exec action=apply auto_approve=true` — ONLY after plan + approval \
8. `terraform_to_inventory` → Ansible configures hosts → verify \
NEVER call apply without running plan first in the same session. \
After user approves apply, call `terraform_exec` again with `auto_approve=true` — \
the approval gate returns NEEDS_APPROVAL, and you must retry with `auto_approve=true`. \
NEVER destroy without explicit user request. State files contain sensitive data.

**TERRAFORM COMPONENT ISOLATION:** \
For single-component infrastructure, use `terraform/main.tf` + `variables.tf` + `outputs.tf`. \
For multi-component infrastructure, scaffold separate modules per bounded domain under \
`terraform/modules/` (networking, compute, platform) each with their own files. \
Root `terraform/main.tf` calls these modules. \
For multi-environment deployments, use `terraform/environments/<env>/` each with their \
own `main.tf` (module calls), `terraform.tfvars`, and `backend.tf` (separate state files). \
Use `generate_terraform backend={type: "s3", bucket: "...", key: "..."}` to configure \
remote state with locking. Use `terraform_exec action=state_mv` for refactoring and \
`action=state_rm` for removing resources from state without destroying them.""",
)

TOPIC_CLOUD_DISCOVERY = TopicDoc(
    name="cloud_discovery",
    keywords=frozenset({
        "discover", "inventory", "aws", "azure", "gcp", "cloud",
        "ec2", "discover_inventory", "terraform_to_inventory",
    }),
    content="""\
**CLOUD DISCOVERY:** \
Use `discover_inventory` for cloud fleets. Install the collection via `manage_galaxy` first. \
Collect credentials via `request_secret` using EXACT env var names the provider expects \
(AWS: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`; Azure: `AZURE_SUBSCRIPTION_ID`, \
`AZURE_CLIENT_ID`, `AZURE_SECRET`, `AZURE_TENANT`; GCP: `GCP_SERVICE_ACCOUNT_FILE`). \
The tool auto-injects vault secrets matching env var names. \
IMPORTANT: `discover_inventory` writes discovered hosts to the infrastructure database AND \
automatically generates a YAML inventory file at `inventory/<source>_hosts.yml`. This file \
is ready for use with `execute_playbook` and `run_adhoc` — no extra `manage_inventory` step \
needed. For Terraform → Ansible handoff, use `terraform_to_inventory` which also writes \
both the DB and inventory files. \
NOTE: Terraform uses DIFFERENT env var names for the same clouds: \
- AWS: same names (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) \
- Azure: `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` (NOT `AZURE_*`) \
- GCP: `GOOGLE_CREDENTIALS`, `GOOGLE_PROJECT`, `GOOGLE_REGION` (NOT `GCP_*`) \
When doing Terraform + Ansible on the same cloud, collect BOTH sets via `request_secret`.""",
)

TOPIC_CICD = TopicDoc(
    name="cicd",
    keywords=frozenset({
        "ci", "cd", "cicd", "ci/cd", "pipeline", "github actions",
        "gitlab", "jenkins", "azure devops", "workflow", "jenkinsfile",
    }),
    content="""\
**CI/CD PIPELINES:** \
Tuyere generates and manages CI/CD pipeline definitions — it does not run CI itself. \
Workflow: \
1. Ask which CI system: GitHub Actions, GitLab CI, Jenkins, Azure DevOps, or other. \
2. Generate pipeline files via `write_file`: \
   - GitHub Actions: `.github/workflows/<name>.yml` \
   - GitLab CI: `.gitlab-ci.yml` \
   - Jenkins: `Jenkinsfile` (declarative pipeline) \
3. Use `render_template` to preview pipeline YAML with variables before writing. \
4. Commit via `manage_git` so the pipeline is immediately active. \
5. For CI runner/agent setup ON infrastructure (Jenkins agents, GitLab runners, GitHub \
   self-hosted runners), use `execute_playbook` or `run_adhoc` with the appropriate modules. \
6. For infrastructure-as-code pipelines (Terraform in CI), generate the pipeline to call \
   `terraform init/plan/apply` with proper state backend config and approval gates. \
Pipeline files are code — validate YAML syntax, use `run_lint` on any Ansible content \
embedded in pipelines, and always include a plan/dry-run stage before apply.""",
)

TOPIC_GITOPS = TopicDoc(
    name="gitops",
    keywords=frozenset({
        "gitops", "argocd", "argo", "flux", "kustomize",
        "application", "sync", "helm", "chart",
    }),
    content="""\
**GITOPS (ArgoCD / Flux):** \
GitOps = Git as single source of truth for cluster state. Tuyere generates the manifests \
and repo structure; the GitOps controller syncs them to the cluster. \
Workflow: \
1. Provision the Kubernetes cluster (Terraform via `generate_terraform` + `terraform_exec`, \
   or Ansible for on-prem). \
2. Install the GitOps controller via `execute_playbook` or Helm (`run_adhoc` with \
   `kubernetes.core.helm` module). Collect kubeconfig via `request_secret`. \
3. Generate application manifests / Kustomize overlays / Helm values via `write_file`. \
4. Structure the repo: `base/` for shared manifests, `overlays/<env>/` for per-environment \
   patches. Use `manage_git` to init, commit, and push. \
5. Generate ArgoCD `Application` or Flux `Kustomization` CRDs via `write_file` pointing \
   at the Git repo path. \
6. For drift: the GitOps controller handles runtime drift. Use `detect_drift` for Ansible-managed \
   nodes outside the cluster. Use `verify_state` to confirm endpoints are healthy post-sync. \
NEVER apply manifests directly to a GitOps-managed cluster with `kubectl apply` — always \
commit to Git and let the controller sync. Direct applies cause drift.""",
)

TOPIC_AIML = TopicDoc(
    name="ai_ml",
    keywords=frozenset({
        "gpu", "cuda", "nvidia", "sagemaker", "bedrock", "vertex",
        "mlflow", "kubeflow", "triton", "vllm", "kserve", "ml",
        "ai", "machine learning", "model", "inference", "training",
        "nfd", "gpu_operator", "openshift ai", "dcgm",
    }),
    content="""\
**AI/ML INFRASTRUCTURE:** \
GPU clusters, managed ML services, and model serving are first-class Tuyere workflows. \
Use Ansible + Terraform together — Terraform provisions the compute, Ansible configures it. \
GPU Cluster Provisioning: \
1. Terraform: provision GPU instances (p5/g6e on AWS, A100/H100 VMs on GCP/Azure) or \
   GPU-enabled K8s clusters via `generate_terraform` + `terraform_exec`. \
2. Ansible: install NVIDIA drivers, CUDA toolkit, NCCL, container runtime on bare metal \
   or VM GPU nodes via `execute_playbook`. Install collection `nvidia.gpu_operator` or \
   use `kubernetes.core.helm` to deploy the NVIDIA GPU Operator on K8s. \
3. For K8s GPU scheduling: GPU Operator handles device plugin, DCGM exporter, MIG manager. \
   Deploy via Helm using `run_adhoc` with `kubernetes.core.helm` module. \
Managed ML Services (Terraform): \
- AWS SageMaker: `aws_sagemaker_domain`, `aws_sagemaker_endpoint`, `aws_sagemaker_model`, \
  `aws_sagemaker_notebook_instance` — provision via `generate_terraform`. \
- AWS Bedrock: `aws_bedrock_*` for foundation model access and agents. \
- Google Vertex AI: `google_vertex_ai_dataset`, `google_vertex_ai_endpoint`, \
  `google_vertex_ai_featurestore` — via `generate_terraform`. \
- Azure ML: `azurerm_machine_learning_workspace`, `azurerm_machine_learning_compute_cluster`. \
- NVIDIA NGC: `terraform-provider-ngc` for NGC Cloud resources. \
ML Platforms on K8s (Ansible + Helm): \
- Install `kubernetes.core` collection via `manage_galaxy`. \
- Deploy Kubeflow, MLflow, Triton Inference Server, vLLM, or KServe via \
  `kubernetes.core.helm` module through `run_adhoc` or `execute_playbook`. \
- Use `request_secret` for kubeconfig, container registry creds, and model API keys. \
AI Collection (Ansible): \
- `amazon.ai`: Bedrock model invocation, agent management, DevOps Guru. \
  Install via `manage_galaxy`, use modules through `run_adhoc` or playbooks. \
Always clarify: training vs inference, managed vs self-hosted, single-GPU vs multi-node. \
GPU driver versions and CUDA versions must match — check compatibility matrix via `web_search` \
before generating automation.""",
)

TOPIC_ONPREM = TopicDoc(
    name="onprem",
    keywords=frozenset({
        "on-prem", "onprem", "data center", "datacenter", "bare metal",
        "baremetal", "switch", "router", "firewall", "ipmi", "redfish",
        "bmc", "netbox", "foreman", "satellite", "netapp", "ceph",
        "san", "nas", "lvm", "pxe", "kickstart", "preseed",
        "cisco", "arista", "juniper", "f5", "palo alto", "fortinet",
        "pure storage", "dell", "hpe",
    }),
    content="""\
**ON-PREM / DATA CENTER INFRASTRUCTURE:** \
Ansible's deepest strength is on-prem. Tuyere handles data centers the same way it handles \
cloud — the target is a hostname/IP instead of a cloud API. \
Inventory for on-prem: \
- For known hosts: use `manage_inventory` to create YAML inventory from hostnames/IPs \
  the user provides. Group by role (webservers, databases, switches, storage). \
- For auto-discovery from IPAM/CMDB: `discover_inventory` works with ANY Ansible inventory \
  plugin, not just cloud. Install the collection via `manage_galaxy`, then call \
  `discover_inventory` with the plugin FQCN and `config_yaml`: \
  - NetBox: plugin_type=`netbox.netbox.nb_inventory`, needs `NETBOX_API` + `NETBOX_TOKEN`. \
  - VMware: plugin_type=`community.vmware.vmware_vm_inventory`, needs vCenter creds. \
  - Foreman/Satellite: plugin_type=`theforeman.foreman.foreman`, needs Foreman URL + creds. \
  - Nmap subnet scan: plugin_type=`community.general.nmap`, provide CIDR ranges in config. \
- Always confirm SSH access method: password vs key, jump host/bastion, non-standard port. \
Network Equipment (switches, routers, firewalls): \
- Install vendor collection via `manage_galaxy` FIRST: \
  Cisco IOS: `cisco.ios`. Cisco NX-OS: `cisco.nxos`. Cisco IOS-XR: `cisco.iosxr`. \
  Arista EOS: `arista.eos`. Juniper Junos: `junipernetworks.junos`. \
  F5 BIG-IP: `f5networks.f5_modules`. Palo Alto: `paloaltonetworks.panos`. \
  Fortinet: `fortinet.fortios`. VyOS: `vyos.vyos`. \
  Base: `ansible.netcommon` (cli_command, cli_config, netconf). \
- Network modules use `ansible_connection: network_cli` or `netconf`, NOT SSH shell. \
  Set connection type in inventory vars. Use `ansible_network_os` to specify platform. \
- Common tasks: backup configs, push config changes, manage VLANs, ACLs, interfaces, \
  routing, NTP, SNMP, firmware upgrades. All via collection modules, NOT shell commands. \
- ALWAYS backup running config before making changes (`*_config` modules with `backup: yes`). \
Storage (SAN, NAS, Object): \
- NetApp ONTAP: `netapp.ontap` — volumes, LUNs, aggregates, snapshots, SVM, CIFS/NFS. \
- Pure Storage: `purestorage.flasharray`, `purestorage.flashblade`. \
- Dell EMC: `dellemc.powerstore`, `dellemc.powerscale`, `dellemc.unity`. \
- Linux storage: `ansible.builtin.mount`, `community.general.lvg`, `community.general.lvol`, \
  `community.general.filesystem` for LVM, NFS mounts, local disk management. \
- Ceph: deploy via playbooks (cephadm), manage via `community.general` or Helm on K8s. \
BMC / Out-of-Band Management: \
- IPMI: `community.general.ipmi_power`, `community.general.ipmi_boot` — power on/off/cycle, \
  set boot device. Requires IPMI credentials via `request_secret`. \
- Redfish (modern BMCs): `community.general.redfish_info`, `community.general.redfish_command`, \
  `community.general.redfish_config` — firmware inventory, power management, BIOS settings. \
- Dell iDRAC: `dellemc.openmanage` collection. HPE iLO: `hpe.oneview`. \
- Use BMC modules for bare-metal lifecycle: power on → PXE boot → OS install → Ansible config. \
Monitoring Stack: \
- Prometheus + Grafana: `prometheus.prometheus` and `grafana.grafana` collections via \
  `manage_galaxy`. Deploy full monitoring stack with `execute_playbook`. \
- Node exporters, DCGM exporter (GPUs), blackbox exporter — all via Ansible roles. \
- Zabbix, Nagios: community roles available via `manage_galaxy`. \
- Use `verify_state` to confirm monitoring endpoints are reachable after deployment. \
Bare Metal Provisioning: \
- Generate kickstart/preseed/cloud-init files via `write_file` + `render_template`. \
- Configure PXE/TFTP/DHCP servers via `execute_playbook`. \
- Workflow: BMC power on → PXE boot → OS auto-install → reboot → Ansible takes over. \
- Tuyere does NOT control the PXE boot process itself — it generates the files and \
  configures the servers that serve them.""",
)

TOPIC_VIRTUALIZATION = TopicDoc(
    name="virtualization",
    keywords=frozenset({
        "vmware", "vsphere", "vcenter", "proxmox", "hyper-v",
        "kvm", "libvirt", "qemu", "esxi", "vm", "virtual machine",
        "hypervisor",
    }),
    content="""\
**VIRTUALIZATION / HYPERVISORS:** \
VMware, Proxmox, Hyper-V, and KVM/libvirt are managed through Ansible collections + Terraform providers. \
Workflow: \
1. Install the collection first via `manage_galaxy`: \
   - VMware: `community.vmware` (requires `pyvmomi`). Terraform: `vsphere` provider. \
   - Proxmox: `community.general` (proxmox* modules). Terraform: `bpg/proxmox` provider. \
   - KVM/libvirt: `community.libvirt`. Terraform: `dmacvicar/libvirt` provider. \
   - Hyper-V: `community.windows` + WinRM connection. \
2. Collect vCenter/API creds via `request_secret` (e.g. `VMWARE_HOST`, `VMWARE_USER`, `VMWARE_PASSWORD`). \
3. Use `run_adhoc` or `execute_playbook` with collection modules for VM lifecycle (create, clone, \
   snapshot, migrate, destroy). Use Terraform via `generate_terraform` + `terraform_exec` for \
   declarative VM provisioning. \
4. After VM creation, use `discover_inventory` or `terraform_to_inventory` to register new VMs \
   as Ansible hosts, then configure them with playbooks. \
NEVER use shell commands for hypervisor CLIs (govc, qm, virsh) — always use the Ansible module.""",
)

ALL_TOPICS: tuple[TopicDoc, ...] = (
    TOPIC_TERRAFORM,
    TOPIC_CLOUD_DISCOVERY,
    TOPIC_CICD,
    TOPIC_GITOPS,
    TOPIC_AIML,
    TOPIC_ONPREM,
    TOPIC_VIRTUALIZATION,
)


def select_topics(user_message: str, max_topics: int = 3) -> list[TopicDoc]:
    lower = user_message.lower()
    scored: list[tuple[int, TopicDoc]] = []
    for topic in ALL_TOPICS:
        hits = sum(1 for kw in topic.keywords if kw in lower)
        if hits > 0:
            scored.append((hits, topic))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [topic for _, topic in scored[:max_topics]]


def build_topic_expansion(user_message: str) -> str:
    topics = select_topics(user_message)
    if not topics:
        return ""
    sections = [t.content for t in topics]
    return "\n\n".join(sections)
