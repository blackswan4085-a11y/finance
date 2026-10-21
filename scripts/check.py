"""Run repository checks with synthetic or isolated inputs; no live AI/API calls."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required for the renderer and JavaScript checks.")
    python_files = [ROOT / "run.py"]
    for folder in ("screener", "scripts", "tests", "earnings/earnings-template"):
        python_files.extend((ROOT / folder).rglob("*.py"))
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    print(f"Python syntax OK: {len(python_files)} files", flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    js_files = sorted((ROOT / "web").rglob("*.js"))
    js_files += sorted((ROOT / "earnings/earnings-template").glob("*.mjs"))
    commands = [[node, "--check", str(path)] for path in js_files]
    commands += [[sys.executable, str(ROOT / "tests" / name)] for name in
                 ("check_screen.py", "check_industry.py", "check_customs.py", "check_earnings.py")]
    commands.append([node, str(ROOT / "tests/check-earnings-table.cjs")])
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode:
            return result.returncode
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
