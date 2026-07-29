"""Reset fixture projects to a pristine, git-initialized state.

Each fixture is a plain directory in the plugin repo (no nested .git committed).
Pipeline runs against a fixture require a git repo with a clean baseline commit;
this script (re)creates that state:

    python tests/fixtures/reset.py             # reset all fixtures
    python tests/fixtures/reset.py ts-todo     # reset one fixture
"""
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
FIXTURES = ["csharp-calculator", "ts-todo", "python-stats"]

CLEAN_DIRS = [
    ".git", ".bob", ".claude", ".worktrees",
    "node_modules", "bin", "obj", "StrykerOutput", "reports",
    ".mutmut-cache", "__pycache__", ".pytest_cache", "coverage", "dist",
]


def run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def reset(name: str) -> None:
    root = FIXTURES_DIR / name
    if not root.is_dir():
        raise SystemExit(f"unknown fixture: {name} (expected one of {FIXTURES})")

    for pattern in CLEAN_DIRS:
        for path in root.rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    run(["git", "init", "-q", "-b", "main"], root)
    run(["git", "add", "-A"], root)
    run(["git", "-c", "user.email=fixture@bob-pipeline.local",
         "-c", "user.name=bob-fixture",
         "commit", "-q", "-m", "fixture baseline"], root)
    print(f"reset: {name}")


if __name__ == "__main__":
    targets = sys.argv[1:] or FIXTURES
    for target in targets:
        reset(target)
