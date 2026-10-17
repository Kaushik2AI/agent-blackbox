"""Publish FlightPath to a Hugging Face Docker Space.

Note: since mid-2026, new Docker Spaces on the free CPU tier need a PRO subscription. The
free deployment is the static showcase on GitHub Pages (docs/deploy.md).

    HF_TOKEN=hf_xxx python infra/space/push.py --space <your-hf-username>/flightpath

Creates the Space if it does not exist, then makes it an exact copy of this repository's
tracked files (one commit; files removed here are removed there), with
infra/space/Dockerfile and infra/space/README.md at the Space's root. The Space builds the
image and serves the app at https://<user>-flightpath.hf.space.

The token needs "write" access (huggingface.co/settings/tokens). It is read from the
environment only and never written anywhere.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE_DIR = ROOT / "infra" / "space"
# Never published, even if tracked: local secrets and data, private notes, screenshots
# (only the GitHub README uses them).
EXCLUDE = [
    ".env",
    ".env.*",
    ".local-data/*",
    "docs/private/*",
    "docs/images/*",
    "*/traces.jsonl",
    "*/node_modules/*",
    "*/.next/*",
    "*__pycache__*",
]
KEEP_REMOTE = {".gitattributes"}


def repo_files() -> list[str]:
    """Tracked files (git), so .gitignore'd data, venvs and builds are never sent."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("run this from a git clone of the repository (needs `git ls-files`)")
    files = [f for f in out.split("\0") if f]
    keep = []
    for f in files:
        if any(fnmatch(f, pat) for pat in EXCLUDE):
            continue
        if f in ("README.md", "Dockerfile") or not (ROOT / f).is_file():
            continue  # replaced by the Space's own versions below; skip deleted files
        keep.append(f)
    return keep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python infra/space/push.py")
    parser.add_argument("--space", required=True, help="<hf-username>/<space-name>")
    parser.add_argument(
        "--dry-run", action="store_true", help="list what would be sent"
    )
    args = parser.parse_args(argv)

    files = repo_files()
    if args.dry_run:
        print("\n".join(files))
        print(f"{len(files)} files + Dockerfile + README.md -> {args.space}")
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit(
            "set HF_TOKEN to a write token from https://huggingface.co/settings/tokens"
        )
    try:
        from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    except ImportError:
        sys.exit("pip install 'huggingface_hub>=0.34' first")

    api = HfApi(token=token)
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    ops: list[CommitOperationAdd | CommitOperationDelete] = [
        CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(ROOT / f)) for f in files
    ]
    ops.append(CommitOperationAdd("Dockerfile", str(SPACE_DIR / "Dockerfile")))
    ops.append(CommitOperationAdd("README.md", str(SPACE_DIR / "README.md")))
    sent = {op.path_in_repo for op in ops}
    remote = set(api.list_repo_files(args.space, repo_type="space"))
    ops += [
        CommitOperationDelete(path_in_repo=f)
        for f in sorted(remote - sent - KEEP_REMOTE)
    ]
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    api.create_commit(
        repo_id=args.space,
        repo_type="space",
        operations=ops,
        commit_message=f"Deploy {sha or 'working tree'}",
    )
    user, name = args.space.split("/", 1)
    print(f"pushed {len(files)} files to https://huggingface.co/spaces/{args.space}")
    print(
        f"it builds now (first time ~10-15 min); then open https://{user}-{name}.hf.space".lower()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
