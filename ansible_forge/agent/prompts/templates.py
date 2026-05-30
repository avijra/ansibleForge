"""Prompt templates for guiding the agent through specific tool workflows."""

PLANNING_PROMPT = """\
Analyze the user's request and determine the best approach.

User request: {user_request}

Consider:
1. What Ansible resources are needed (playbooks, roles, inventory)?
2. Are there any Galaxy collections required?
3. What hosts/groups are targeted?
4. Are there any secrets that need vault encryption?
5. What is the execution order?

Respond by calling the appropriate tools in sequence. Start with generation,
then lint, then dry-run. Do NOT execute without user approval.
"""

PLAYBOOK_CONTEXT = """\
Current workspace: {workspace_path}
Project files:
  inventory/: {inventory_files}
  playbooks/: {playbook_files}
  roles/: {role_names}
  terraform/: {terraform_files}
{extra_files}"""

LINT_FIX_PROMPT = """\
The following ansible-lint violations were found:

{violations}

Fix each violation by regenerating the affected playbook with corrections applied.
Use FQCN for all modules, add names to all tasks, and follow Ansible best practices.

When you present the lint results, format them as a professional report:
- Use ### 🧹 Lint Results as the heading
- List each violation with ❌ or ⚠️ status, the rule name in backticks, and a clear fix description
- End with a summary of total violations found and fixed
"""

ERROR_RECOVERY_PROMPT = """\
The previous action failed:

Tool: {tool_name}
Error: {error_message}

CRITICAL INSTRUCTION: You MUST fix this yourself. Do NOT just report the error to the user. \
Do NOT ask the user to fix it. You are an expert — diagnose and repair autonomously.

Follow this recovery procedure:
1. Identify the root cause from the error message.
2. If a playbook failed, use `read_file` to read the failing playbook FIRST. Do NOT \
regenerate from scratch — read it, find the broken task, and surgically fix only that task. \
Full regeneration loses working tasks and introduces new bugs.
3. If you are unsure how to fix it, use the `web_search` tool to look up the error message \
or the correct module usage. Search Ansible docs, Stack Overflow, or general web for \
solutions. Learn from the search results and apply the fix.
4. Fix the issue by calling the appropriate tools.
5. Re-run the failed action after fixing.
6. Only report to the user AFTER you have attempted the fix.

Common fixes — execute these yourself, do not just list them:
- Missing template file → generate the template file with generate_playbook, then retry
- Missing collection → install it with manage_galaxy, then retry
- Syntax error → read_file the playbook, fix the syntax, overwrite with generate_playbook, retry
- HTTP 304 / download issue → add `force: true` or `status_code: [200, 304]` to the task, \
fix in-place, then retry
- Host unreachable → check the inventory file is correct, fix connectivity params, retry. \
If the error mentions "Broken pipe" or SSH auth failure, secrets may be missing from the vault \
(they expire after restart). Use `request_secret` to re-collect credentials, then retry.
- "secrets not in the vault" → use `request_secret` to collect each missing secret, then retry
- Broken pipe / Errno 32 → this is almost NEVER a crashed runner. It's usually SSH auth failing \
because credentials are missing. Check if your inventory uses {{{{ variables }}}} and whether those \
secrets are available. Use `test_connectivity` or `run_adhoc` with `ansible.builtin.ping` to \
verify SSH access. If it's a permission issue, re-request the secret via `request_secret`.
- Permission denied → add `become: true` to the task, fix in-place, retry
- Module not found → use web_search to find the correct FQCN, fix in-place, retry
- File not found → create the missing file, then retry
- Unknown error → use web_search with the error message to find the solution

You have {remaining_retries} retries remaining for this error. USE THEM. \
Search the web if you need to learn something before retrying.
"""

DRY_RUN_REVIEW_PROMPT = """\
Dry-run completed. Here is the change summary:

{diff_summary}

Present this to the user as a professional dry-run report:
- Use ### 🔍 Dry-Run Results as the heading
- Show the playbook name, target hosts, and mode
- List each change with ✅ (ok), 🔄 (changed), or ⏭️ (skipped) status indicators
- Highlight any destructive changes with ⚠️ and bold text
- Show the diff in a ```diff code block if available
- End with a clear approval prompt asking the user to confirm execution
"""
