#!/usr/bin/env python3
"""SageMaker serving shim for Strands Decider 2B.

SageMaker real-time endpoints require a container that answers:
  * GET  /ping         -> 200 once the model is ready
  * POST /invocations  -> the inference call

Kiro Crew's sagemaker:// decision route (impl_sagemaker.py) sends the SAME JSON
body its HTTP Jev client sends to ``/v1/systemone``:

    {"state": <dict|str>, "model": "strands-decider-2b", "questions": {<id>: {...}}}

with ContentType application/json, and expects the /v1/systemone response JSON
back. Image/Box requests arrive with CustomAttributes
"TypeSafe-Danger-Zone-Images=true" (SageMaker maps that to the
X-Amzn-SageMaker-Custom-Attributes header); the strands server reads no such
header, so we simply forward the body -- images travel inside it as assets.

This shim loads the Strands app via ``strands_decider.server.create_app`` (the
exact entrypoint Kiro Crew's local launcher uses) pointed at the model dir
SageMaker extracts to ``/opt/ml/model``, and applies the same null-criteria
normalization Kiro Crew's launcher applies (an option with rubric ``null`` ->
""), because the gate sends null rubrics and the strands schema 422s on them.

Env:
  MODEL_DIR  model directory (default /opt/ml/model, SageMaker's mount)
  PORT       port to listen on (default 8080, SageMaker's expected port)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

MODEL_DIR = os.environ.get("MODEL_DIR", "/opt/ml/model")

# The checkpoint config names its base by Hub id; the server would otherwise try
# the Hub. Point it at the mirrored base/ dir, exactly as strands_decider_cpu.py does.
BASE_DIR = os.path.join(MODEL_DIR, "base")


def _blank_null_criteria(body: bytes) -> bytes:
    """Kiro Crew sends an option with no rubric as ``null``; strands' schema types
    every rubric as a string and 422s a null one. An empty rubric means the same.
    Identical to strands_decider_cpu.py's _blank_null_criteria."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, dict):
        return body
    for question in questions.values():
        criteria = question.get("criteria") if isinstance(question, dict) else None
        if isinstance(criteria, dict):
            for option, rubric in criteria.items():
                if rubric is None:
                    criteria[option] = ""
    return json.dumps(data).encode()


def build() -> FastAPI:
    from strands_decider import modeling
    from strands_decider.server import create_app

    _from_json = modeling.StrandsDeciderConfig.from_json

    def _from_json_local_base(path: str):
        config = _from_json(path)
        config.base_model = BASE_DIR
        return config

    modeling.StrandsDeciderConfig.from_json = staticmethod(_from_json_local_base)  # type: ignore

    inner = create_app(MODEL_DIR, device="cpu", model_name="strands-decider-2b")

    app = FastAPI()

    @app.get("/ping")
    def ping() -> Response:
        # Model weights are loaded by create_app() at import time above; if we got
        # here the app is built, so report healthy.
        return PlainTextResponse("", status_code=200)

    @app.post("/invocations")
    async def invocations(request: Request) -> Response:
        raw = await request.body()
        body = _blank_null_criteria(raw)
        # Dispatch to the inner strands app's /v1/systemone via its ASGI interface,
        # so no second HTTP port or process is needed.
        payload_holder: dict = {"status": 500, "headers": [], "body": b""}

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/v1/systemone",
            "raw_path": b"/v1/systemone",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"accept", b"application/json"),
            ],
            "server": ("127.0.0.1", 8080),
            "client": ("127.0.0.1", 0),
            "scheme": "http",
        }
        sent = {"done": False}

        async def receive():
            if sent["done"]:
                return {"type": "http.disconnect"}
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        chunks = []

        async def send(message):
            if message["type"] == "http.response.start":
                payload_holder["status"] = message["status"]
                payload_holder["headers"] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await inner(scope, receive, send)
        out = b"".join(chunks)
        ct = "application/json"
        for k, v in payload_holder["headers"]:
            if k.lower() == b"content-type":
                ct = v.decode()
        return Response(content=out, status_code=payload_holder["status"], media_type=ct)

    return app


app = build()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="warning")
