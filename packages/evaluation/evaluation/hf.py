"""Run a Qwen-style instruct model with Hugging Face transformers, in-process.

Used by GPU batch runs (evaluation.benchmark --model hf:<id>) and by the app's local
model server (infra/local/qwen_server.py). Imports torch/transformers lazily, so the rest
of the package works without them.
"""

from __future__ import annotations

import importlib
import os
import threading
import time
from typing import Any

from agent_harness.llm import LLMConfig, OpenAICompatModel

SMALL, MEDIUM, LARGE = (
    "Qwen/Qwen2.5-0.5B-Instruct",
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
)


def mem_available_gb() -> float:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 0.0


def choose_model(requested: str, gpu_mem_gb: float | None, ram_gb: float) -> str:
    """Pick a model that fits. `gpu_mem_gb` is None when there is no usable GPU."""
    if requested and requested != "auto":
        return requested
    if gpu_mem_gb is not None:
        return LARGE if gpu_mem_gb >= 12 else MEDIUM
    return MEDIUM if ram_gb >= 10 else SMALL


def json_complete(text: str) -> bool:
    """True once `text` contains a balanced top-level {...} (strings respected)."""
    depth = 0
    in_str = esc = False
    seen = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == "{":
            depth += 1
            seen = True
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and seen:
                return True
    return False


class HFGenerator:
    """Loads one model; generates one reply at a time (thread-safe)."""

    def __init__(self, requested: str = "auto", revision: str | None = None) -> None:
        self.requested = requested
        self.revision = revision
        self.status = "loading"
        self.error = ""
        self.model_id = ""
        self.device = ""
        self.dtype = ""
        self.resolved_revision: str | None = None
        self.loaded_in_s = 0.0
        self._lock = threading.Lock()
        self._tok: Any = None
        self._model: Any = None

    def load(self) -> None:
        started = time.time()
        try:
            torch: Any = importlib.import_module("torch")
            transformers: Any = importlib.import_module("transformers")
            AutoModelForCausalLM = transformers.AutoModelForCausalLM  # noqa: N806
            AutoTokenizer = transformers.AutoTokenizer  # noqa: N806

            gpu_mem: float | None = None
            if torch.cuda.is_available():
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            self.device = "cuda" if gpu_mem is not None else "cpu"
            self.model_id = choose_model(self.requested, gpu_mem, mem_available_gb())
            if self.device == "cpu":
                slots = int(
                    os.environ.get("NSLOTS")
                    or os.environ.get("SLURM_CPUS_PER_TASK")
                    or os.cpu_count()
                    or 1
                )
                torch.set_num_threads(max(1, slots))
                dtype = torch.float32  # bf16 matmuls are slow on most server CPUs
            else:
                dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            self.dtype = str(dtype).removeprefix("torch.")
            kwargs: dict[str, Any] = {"revision": self.revision} if self.revision else {}
            self._tok = AutoTokenizer.from_pretrained(self.model_id, **kwargs)
            model = AutoModelForCausalLM.from_pretrained(self.model_id, dtype=dtype, **kwargs)
            self._model = model.to(self.device).eval()
            self.resolved_revision = getattr(model.config, "_commit_hash", None) or self.revision
            self.loaded_in_s = round(time.time() - started, 1)
            self.status = "ready"
        except Exception as exc:  # reported to the caller; never crashes a server thread
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"[:500]

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
    ) -> dict[str, Any]:
        torch: Any = importlib.import_module("torch")
        transformers: Any = importlib.import_module("transformers")

        tok, model = self._tok, self._model
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt, return_tensors="pt").to(self.device)
        n_in = int(inputs["input_ids"].shape[1])

        class StopAtJson(transformers.StoppingCriteria):  # type: ignore[misc]
            def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
                return json_complete(tok.decode(input_ids[0, n_in:], skip_special_tokens=True))

        kwargs: dict[str, Any] = {
            "max_new_tokens": max(16, min(int(max_tokens), 1024)),
            "stopping_criteria": transformers.StoppingCriteriaList([StopAtJson()]),
            "pad_token_id": tok.eos_token_id,
        }
        if temperature > 0:
            kwargs.update(do_sample=True, temperature=float(temperature), top_p=0.9)
        else:
            kwargs.update(do_sample=False)
        with self._lock, torch.inference_mode():
            if seed is not None:
                torch.manual_seed(seed)
            out = model.generate(**inputs, **kwargs)
        new = out[0, n_in:]
        return {
            "text": tok.decode(new, skip_special_tokens=True),
            "prompt_tokens": n_in,
            "completion_tokens": int(new.shape[0]),
        }


class TransformersModel(OpenAICompatModel):
    """The agent's model protocol, answered by a local transformers model. Same prompt,
    same JSON action format and same parsing as the hosted-API adapter."""

    def __init__(self, generator: HFGenerator, temperature: float, max_tokens: int) -> None:
        super().__init__(
            LLMConfig(
                base_url="local://transformers",
                api_key="",
                model=generator.model_id,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        self.generator = generator
        self.seed: int | None = None

    def reseed(self, seed: int) -> TransformersModel:
        self.seed = seed
        return self

    def decision_seed(self, messages: list[dict[str, str]]) -> int | None:
        """The sampling seed of one decision depends only on the run's seed and how far
        the conversation is (its length). A run restarted from a saved step therefore
        draws exactly the samples the original run drew from that step on, so a replay
        with nothing changed can reproduce it, and the arms differ only by their change."""
        return None if self.seed is None else self.seed + len(messages)

    def _complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
        cfg = self.config
        out = self.generator.chat(
            messages, cfg.temperature, cfg.max_tokens, self.decision_seed(messages)
        )
        text = "".join(ch for ch in out["text"] if ch >= " " or ch in "\n\t")
        return text, {
            "input_tokens": out["prompt_tokens"],
            "output_tokens": out["completion_tokens"],
        }
