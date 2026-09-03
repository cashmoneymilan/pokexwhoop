"""Release verification for the WHOOP daily data pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(name: str, command: list[str]) -> bool:
    result = subprocess.run(command, cwd=ROOT, text=True)
    passed = result.returncode == 0
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return passed


def check(name: str, condition: bool) -> bool:
    print(f"{'PASS' if condition else 'FAIL'}: {name}")
    return condition


def main() -> int:
    results = [
        run("Python modules compile", [sys.executable, "-m", "py_compile", "server.py", "whoop_client.py", "database.py", "daily_pipeline.py", "policy.py"]),
        run("Unit and route integration tests pass", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        run("Git patch has no whitespace errors", ["git", "diff", "--check"]),
    ]
    overrides = json.loads((ROOT / "whoop_overrides.json").read_text(encoding="utf-8"))
    results.append(check("August 23 is explicitly invalidated", overrides.get("2026-08-23", {}).get("invalidated") is True))
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    results.append(check("MCP compatibility boundary is pinned", "mcp>=1.26,<2" in requirements))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
