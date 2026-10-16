"""Explicit environment checks before a (GPU) benchmark run.

    python -m evaluation.envcheck                 # print a report, exit 1 on a hard failure
    python -m evaluation.envcheck --require-gpu   # also fail when no GPU is visible

Checks: Python version, packages, model cache location (must be writable and, by
default, not in $HOME, which is often small on shared machines), torch/CUDA and the GPU,
and the scheduler job id when running as a batch job.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any


def job_id() -> str | None:
    for var in ("JOB_ID", "SLURM_JOB_ID", "PBS_JOBID", "LSB_JOBID"):
        if os.environ.get(var):
            return f"{var}={os.environ[var]}"
    return None


def environment(device_info: bool = True) -> dict[str, Any]:
    # Deliberately no host name: results get committed and shared, and the scheduler job
    # id is enough to find the job again.
    env: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(terse=True),
        "job_id": job_id(),
    }
    if device_info:
        try:
            torch = importlib.import_module("torch")
            env["torch"] = torch.__version__
            env["cuda"] = torch.version.cuda
            env["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            env["gpu_count"] = torch.cuda.device_count() if torch.cuda.is_available() else 0
        except ImportError:
            env["torch"] = None
        try:
            env["transformers"] = importlib.import_module("transformers").__version__
        except ImportError:
            env["transformers"] = None
    return env


def check(require_gpu: bool, allow_home_cache: bool) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    env = environment()
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        errors.append(f"Python {env['python']}: need 3.11 or 3.12")
    if env.get("torch") is None:
        errors.append("torch is not installed (pip install -e 'packages/evaluation[gpu]')")
    if env.get("transformers") is None:
        errors.append("transformers is not installed (pip install -e 'packages/evaluation[gpu]')")
    if require_gpu and not env.get("gpu"):
        errors.append(
            "no GPU visible to torch (CUDA_VISIBLE_DEVICES, driver, or a CPU-only torch build)"
        )
    cache = Path(
        os.environ.get("HF_HUB_CACHE")
        or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    )
    env["hf_cache"] = str(cache)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        probe = cache / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        errors.append(
            f"model cache {cache} is not writable ({exc.__class__.__name__}); "
            "set HF_HOME / HF_HUB_CACHE"
        )
    if not allow_home_cache and str(cache).startswith(str(Path.home())):
        warnings.append(
            f"model cache is under $HOME ({cache}); "
            "set HF_HOME to project storage if $HOME is small"
        )
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        warnings.append(
            "a Hugging Face token is set; it is never written to results "
            "(public Qwen models do not need one)"
        )
    return errors, warnings, env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.envcheck")
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--allow-home-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    errors, warnings, env = check(args.require_gpu, args.allow_home_cache)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "environment": env}, indent=2))
    else:
        for k, v in env.items():
            print(f"  {k:<13} {v}")
        for w in warnings:
            print(f"WARNING: {w}")
        for e in errors:
            print(f"ERROR: {e}")
        print("environment OK" if not errors else "environment NOT ready")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
