export const toolLabels: Record<string, string> = {
  generate_playbook: "Generating Playbook",
  scaffold_role: "Scaffolding Role",
  manage_inventory: "Managing Inventory",
  manage_vault: "Encrypting Secrets",
  run_lint: "Checking Code Quality",
  run_molecule: "Running Tests",
  manage_galaxy: "Managing Packages",
  execute_playbook: "Running Deployment",
  collect_facts: "Gathering System Info",
  search_docs: "Searching Documentation",
  web_search: "Searching the Web",
  write_file: "Writing File",
  request_secret: "Requesting Credentials",
  run_adhoc: "Running Command",
  detect_drift: "Checking for Drift",
  scan_compliance: "Running Security Scan",
  terraform_exec: "Running Terraform",
  terraform_to_inventory: "Importing Terraform Hosts",
  generate_terraform: "Generating Terraform Config",
  discover_inventory: "Discovering Hosts",
  render_template: "Previewing Template",
  manage_git: "Git Operation",
  inspect_variables: "Inspecting Variables",
  compare_configs: "Comparing Configurations",
  manage_schedule: "Managing Schedule",
  import_project: "Importing Project",
  analyze_logs: "Analyzing Run History",
  generate_rollback: "Generating Rollback Plan",
  verify_state: "Verifying State",
  test_connectivity: "Testing Connection",
};

export function friendlyToolName(tool: string): string {
  return toolLabels[tool] || tool;
}

function stripModule(fqcn: string): string {
  const parts = fqcn.split(".");
  return parts[parts.length - 1];
}

function hostLabel(pattern: unknown): string {
  if (!pattern || pattern === "all") return "all hosts";
  return String(pattern);
}

export function describeToolCall(
  tool: string,
  args: Record<string, unknown> | undefined,
): string {
  if (!args) return toolLabels[tool] || tool;

  switch (tool) {
    case "run_adhoc": {
      const mod = stripModule(String(args.module || "command"));
      const target = hostLabel(args.host_pattern);
      return `Running ${mod} on ${target}`;
    }
    case "execute_playbook": {
      const pb = String(args.playbook || "playbook");
      const name = pb.split("/").pop() || pb;
      const mode = args.check_mode ? " (preview)" : "";
      return `Running ${name}${mode}`;
    }
    case "collect_facts":
      return `Gathering system info from ${hostLabel(args.host_pattern)}`;
    case "test_connectivity":
      return `Testing connection to ${hostLabel(args.host_pattern)}`;
    case "terraform_exec": {
      const actionMap: Record<string, string> = {
        init: "Initializing infrastructure tools",
        plan: "Planning infrastructure changes",
        apply: "Applying infrastructure changes",
        destroy: "Destroying infrastructure",
        output: "Reading infrastructure outputs",
        state: "Inspecting infrastructure state",
        validate: "Validating configuration",
        fmt: "Formatting configuration files",
      };
      return actionMap[String(args.action)] || `Terraform ${args.action}`;
    }
    case "generate_terraform": {
      const file = String(args.filename || "config");
      return `Writing Terraform file ${file}`;
    }
    case "terraform_to_inventory":
      return `Converting Terraform resources to host inventory`;
    case "discover_inventory": {
      const plugin = String(args.plugin_type || "cloud");
      const provider = plugin.includes("aws") ? "AWS" :
        plugin.includes("azure") ? "Azure" :
        plugin.includes("gcp") ? "GCP" :
        plugin.includes("digitalocean") ? "DigitalOcean" :
        plugin.split(".").pop() || "cloud";
      return `Discovering hosts from ${provider}`;
    }
    case "generate_playbook": {
      const name = String(args.playbook_name || "playbook");
      return `Writing playbook ${name}`;
    }
    case "manage_inventory": {
      const action = String(args.action || "update");
      if (action === "create") return "Creating server inventory";
      if (action === "add_host") return `Adding ${args.host || "host"} to inventory`;
      if (action === "add_group") return `Adding group ${args.group || ""} to inventory`;
      return "Reading server inventory";
    }
    case "manage_git": {
      const gitAction = String(args.action || "status");
      const gitLabels: Record<string, string> = {
        init: "Initializing repository",
        status: "Checking repository status",
        diff: "Viewing changes",
        add: "Staging files",
        commit: "Committing changes",
        log: "Viewing commit history",
        branch: "Managing branches",
        checkout: "Switching branch",
        push: "Pushing to remote",
        pull: "Pulling from remote",
        stash: "Stashing changes",
      };
      return gitLabels[gitAction] || `Git ${gitAction}`;
    }
    case "write_file": {
      const fp = String(args.file_path || "file");
      return `Writing ${fp.split("/").pop() || fp}`;
    }
    case "manage_galaxy": {
      const gAction = String(args.action || "list");
      if (gAction === "install") return `Installing package ${args.collection_name || ""}`.trim();
      if (gAction === "list") return "Listing installed packages";
      if (gAction === "search") return `Searching for ${args.query || "packages"}`;
      return `Managing packages`;
    }
    case "scan_compliance": {
      const profiles = args.profiles as string[] | undefined;
      const target = hostLabel(args.host_pattern);
      const what = profiles?.length ? profiles.join(", ") : "security";
      return `Scanning ${target} for ${what} compliance`;
    }
    case "compare_configs": {
      const file = String(args.file_path || "config");
      return `Comparing ${file.split("/").pop()} across hosts`;
    }
    case "detect_drift": {
      const pb = String(args.playbook || "configuration");
      return `Checking ${pb.split("/").pop() || pb} for drift`;
    }
    case "request_secret": {
      const forHost = args.for_host ? ` for ${args.for_host}` : "";
      return `Requesting ${args.sensitive_type || "credentials"}${forHost}`;
    }
    case "render_template":
      return `Previewing template ${String(args.template_path || args.template_name || "").split("/").pop() || ""}`.trim();
    case "inspect_variables":
      return `Inspecting variable precedence on ${args.hostname || "host"}`;
    case "analyze_logs": {
      const logAction = String(args.analysis_type || "overview");
      const logLabels: Record<string, string> = {
        overview: "Analyzing run history overview",
        failures: "Analyzing recent failures",
        host_health: "Checking host health trends",
        playbook_stats: "Analyzing playbook statistics",
        trends: "Analyzing activity trends",
      };
      return logLabels[logAction] || "Analyzing run history";
    }
    case "import_project":
      return `Importing project from ${args.git_url || args.source_path || "source"}`;
    case "manage_schedule": {
      const sAction = String(args.action || "list");
      if (sAction === "create") return `Scheduling ${args.name || "job"}`;
      if (sAction === "list") return "Listing scheduled jobs";
      if (sAction === "delete") return "Removing scheduled job";
      return `Updating schedule`;
    }
    case "scaffold_role":
      return `Creating role structure for ${args.role_name || "role"}`;
    case "manage_vault": {
      const vAction = String(args.action || "encrypt");
      if (vAction === "encrypt") return "Encrypting file";
      if (vAction === "decrypt") return "Decrypting file";
      return `Vault ${vAction}`;
    }
    case "run_lint":
      return `Checking code quality of ${String(args.target || "files").split("/").pop()}`;
    case "search_docs":
      return `Searching docs for "${args.query || args.module || ""}"`;
    case "verify_state":
      return `Verifying expected state on ${hostLabel(args.host_pattern)}`;
    case "generate_rollback":
      return `Creating rollback plan for ${String(args.playbook || "deployment").split("/").pop()}`;
    default:
      return toolLabels[tool] || tool;
  }
}
