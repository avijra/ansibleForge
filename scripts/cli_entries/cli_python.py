"""Minimal Python script executor for Ansible module execution.

This is NOT a full Python interpreter. It supports the invocation patterns
Ansible uses when running modules on localhost via the local connection:
  1. ansible-python /path/to/ansiballz_script.py
  2. ansible-python -c "inline code"

Because this is a PyInstaller-bundled binary it has access to all packages
in _internal/ (boto3, ansible, etc.) without needing a system-wide install.
Additionally, packages auto-installed by the dep_manager into
~/.ansibleforge/site-packages/ are available via sys.path injection.
"""
import os
import runpy
import sys


def main() -> None:
    # Make auto-installed packages (boto3, kubernetes, etc.) importable
    managed_sp = os.path.join(os.path.expanduser("~"), ".ansibleforge", "site-packages")
    if os.path.isdir(managed_sp) and managed_sp not in sys.path:
        sys.path.insert(0, managed_sp)

    if len(sys.argv) < 2:
        sys.exit("Usage: ansible-python <script.py> | -c <code>")

    if sys.argv[1] == "-c":
        if len(sys.argv) < 3:
            sys.exit("Missing code after -c")
        code = sys.argv[2]
        sys.argv = ["-c", *sys.argv[3:]]
        exec(compile(code, "<string>", "exec"))  # noqa: S102
    else:
        script = sys.argv[1]
        sys.argv = sys.argv[1:]
        runpy.run_path(script, run_name="__main__")


main()
