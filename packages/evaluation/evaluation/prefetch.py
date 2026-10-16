"""Download a model into the Hugging Face cache ahead of a batch job.

    python -m evaluation.prefetch Qwen/Qwen2.5-3B-Instruct [--revision <commit>]

Prints the resolved commit, which the benchmark records with every run.
"""

from __future__ import annotations

import argparse
import importlib
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.prefetch")
    parser.add_argument("model")
    parser.add_argument("--revision", default=None)
    args = parser.parse_args(argv)
    hub: Any = importlib.import_module("huggingface_hub")
    path = hub.snapshot_download(
        args.model,
        revision=args.revision,
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "merges.txt"],
    )
    print(f"{args.model} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
