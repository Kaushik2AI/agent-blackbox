"""A small OpenAI-compatible chat server that runs a Qwen model on this machine (GPU
or CPU) with Hugging Face transformers. The live demo talks to it exactly as it would
talk to a hosted API, so nothing else in the app knows the model is local.

    python infra/local/qwen_server.py            # started for you by `make dev` when
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

# Model loading and generation are shared with GPU benchmark runs (evaluation.hf).
from evaluation.hf import LARGE, MEDIUM, SMALL, HFGenerator, choose_model, json_complete  # noqa: F401


def short_label(model_id: str, device: str) -> str:
    name = model_id.rsplit("/", 1)[-1].replace("-Instruct", "").replace("-", " ")
    return f"{name} (local {'GPU' if device == 'cuda' else 'CPU'})"


class Engine(HFGenerator):
    """HFGenerator that logs what it does (the server's log is the user's only window)."""

    def load(self) -> None:
        log(f"loading {self.requested} ...")
        super().load()
        if self.status == "ready":
            log(f"ready: {self.model_id} on {self.device} ({self.dtype}) in {self.loaded_in_s}s")
        else:
            log(f"FAILED to load model: {self.error}")


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
