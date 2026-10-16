"""A small OpenAI-compatible chat server that runs a Qwen model on this machine (SCC GPU
or CPU) with Hugging Face transformers. The live demo talks to it exactly as it would
talk to a hosted API, so nothing else in the app knows the model is local.

    python infra/scc/qwen_server.py            # started for you by `make dev` when
                                               # QWEN_LOCAL=1 is in .env (`make qwen-setup`)

Endpoints (127.0.0.1 only, bearer token = LLM_API_KEY):
    GET  /health                 {"status": "loading" | "ready" | "error", ...}  (no token)
    GET  /v1/models
    POST /v1/chat/completions    messages, temperature, max_tokens

Settings (environment):
    QWEN_MODEL    Hugging Face model id, or "auto" (default): Qwen2.5-3B-Instruct on a GPU
                  with >= 12 GB, Qwen2.5-1.5B-Instruct on a smaller GPU or a CPU with
                  >= 10 GB free RAM, otherwise Qwen2.5-0.5B-Instruct.
    QWEN_PORT     port (default 8001)
    HF_HOME       where weights are cached (the Makefile points it into the repo, so the
                  download counts against project space, not your home quota)

Generation stops as soon as the reply contains one complete JSON object, because that is
all the agent asks for; on a CPU this saves most of the time.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
import uuid
from typing import Any

from pydantic import BaseModel  # installed with the API (FastAPI depends on it)

SMALL, MEDIUM, LARGE = (
    "Qwen/Qwen2.5-0.5B-Instruct",
    "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen/Qwen2.5-3B-Instruct",
)


def _mem_available_gb() -> float:
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


def short_label(model_id: str, device: str) -> str:
    name = model_id.rsplit("/", 1)[-1].replace("-Instruct", "").replace("-", " ")
    return f"{name} · on SCC {'GPU' if device == 'cuda' else 'CPU'}"


class Engine:
    """Loads the model in a background thread; generates one request at a time."""

    def __init__(self, requested: str) -> None:
        self.requested = requested
        self.status = "loading"
        self.error = ""
        self.model_id = ""
        self.device = ""
        self.loaded_in_s = 0.0
        self._lock = threading.Lock()
        self._tok: Any = None
        self._model: Any = None

    def load(self) -> None:
        started = time.time()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            gpu_mem: float | None = None
            if torch.cuda.is_available():
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            self.device = "cuda" if gpu_mem is not None else "cpu"
            self.model_id = choose_model(self.requested, gpu_mem, _mem_available_gb())
            if self.device == "cpu":
                slots = int(os.environ.get("NSLOTS") or os.cpu_count() or 1)
                torch.set_num_threads(max(1, slots))
                dtype = torch.float32  # bf16 matmuls are slow on most SCC CPUs
            else:
                dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            log(f"loading {self.model_id} on {self.device} ({dtype}) ...")
            self._tok = AutoTokenizer.from_pretrained(self.model_id)
            model = AutoModelForCausalLM.from_pretrained(self.model_id, dtype=dtype)
            self._model = model.to(self.device).eval()
            self.loaded_in_s = round(time.time() - started, 1)
            self.status = "ready"
            log(f"ready: {self.model_id} on {self.device} in {self.loaded_in_s}s")
        except Exception as exc:  # reported on /health, the app shows "offline"
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"[:500]
            log(f"FAILED to load model: {self.error}")

    def chat(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> dict:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        tok, model = self._tok, self._model
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt, return_tensors="pt").to(self.device)
        n_in = int(inputs["input_ids"].shape[1])

        class StopAtJson(StoppingCriteria):
            def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
                text = tok.decode(input_ids[0, n_in:], skip_special_tokens=True)
                return json_complete(text)

        kwargs: dict[str, Any] = {
            "max_new_tokens": max(16, min(int(max_tokens), 1024)),
            "stopping_criteria": StoppingCriteriaList([StopAtJson()]),
            "pad_token_id": tok.eos_token_id,
        }
        if temperature > 0:
            kwargs.update(do_sample=True, temperature=float(temperature), top_p=0.9)
        else:
            kwargs.update(do_sample=False)
        with self._lock, torch.inference_mode():
            out = model.generate(**inputs, **kwargs)
        new = out[0, n_in:]
        text = tok.decode(new, skip_special_tokens=True)
        return {"text": text, "prompt_tokens": n_in, "completion_tokens": int(new.shape[0])}


class Msg(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    model: str = ""
    messages: list[Msg]
    temperature: float = 0.2
    max_tokens: int = 256


def log(msg: str) -> None:
    print(f"[qwen {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_app(engine: Engine, api_key: str) -> Any:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Local Qwen (OpenAI-compatible)", docs_url=None, redoc_url=None)

    def check(auth: str | None) -> None:
        expected = f"Bearer {api_key}"
        if not auth or not secrets.compare_digest(auth, expected):
            raise HTTPException(401, "bad or missing API key")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": engine.status,
            "model": engine.model_id,
            "device": engine.device,
            "label": short_label(engine.model_id, engine.device) if engine.model_id else "",
            "error": engine.error,
        }

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> Any:
        check(authorization)
        if engine.status != "ready":
            return JSONResponse({"status": engine.status, "error": engine.error}, status_code=503)
        return {
            "object": "list",
            "data": [
                {
                    "id": engine.model_id,
                    "object": "model",
                    "owned_by": "local",
                    "label": short_label(engine.model_id, engine.device),
                }
            ],
        }

    @app.post("/v1/chat/completions")
    def chat(body: ChatIn, authorization: str | None = Header(default=None)) -> Any:
        check(authorization)
        if engine.status != "ready":
            raise HTTPException(503, f"model is {engine.status}")
        started = time.perf_counter()
        result = engine.chat(
            [m.model_dump() for m in body.messages], body.temperature, body.max_tokens
        )
        log(
            f"chat: {result['prompt_tokens']} in / {result['completion_tokens']} out "
            f"in {time.perf_counter() - started:.1f}s"
        )
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": engine.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result["text"]},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "total_tokens": result["prompt_tokens"] + result["completion_tokens"],
            },
        }

    return app


def main() -> None:
    import uvicorn

    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        sys.exit("LLM_API_KEY is not set (run `make qwen-setup`)")
    port = int(os.environ.get("QWEN_PORT", "8001"))
    engine = Engine(os.environ.get("QWEN_MODEL", "auto"))
    threading.Thread(target=engine.load, daemon=True).start()
    uvicorn.run(build_app(engine, api_key), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
