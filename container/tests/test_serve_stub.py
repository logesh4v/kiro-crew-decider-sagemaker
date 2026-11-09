#!/usr/bin/env python3
"""Stub test for serve.py: SageMaker contract + null-criteria normalization.

Does NOT load the 2B model. It mocks strands_decider so build() constructs the
FastAPI app with a stub inner ASGI app that echoes the body it received. We then
assert:
  * GET /ping            -> 200
  * POST /invocations    -> inner app received the body (forwarded), with null
                            option rubrics rewritten to "" (the gate sends null),
                            and the inner JSON response is returned verbatim.

Run from the repo root:  python3 container/tests/test_serve_stub.py
or with pytest:          pytest container/tests/
"""
import json
import os
import sys

# serve.py lives one directory up (container/); make it importable whichever
# directory the test is launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import types


def install_strands_stub(captured: dict):
    """Install a fake strands_decider package whose create_app returns an ASGI app
    that captures the request body and replies with the parsed JSON echoed back."""
    pkg = types.ModuleType("strands_decider")
    modeling = types.ModuleType("strands_decider.modeling")
    server = types.ModuleType("strands_decider.server")

    class StrandsDeciderConfig:
        base_model = ""

        @staticmethod
        def from_json(path):
            return StrandsDeciderConfig()

    modeling.StrandsDeciderConfig = StrandsDeciderConfig

    def create_app(model_dir, device="cpu", model_name=""):
        async def inner(scope, receive, send):
            body = b""
            while True:
                msg = await receive()
                body += msg.get("body", b"")
                if not msg.get("more_body"):
                    break
            captured["path"] = scope["path"]
            captured["body"] = body
            parsed = json.loads(body)
            resp = json.dumps({"answers": {"echo": parsed}}).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": resp})
        return inner

    server.create_app = create_app
    pkg.modeling = modeling
    pkg.server = server
    sys.modules["strands_decider"] = pkg
    sys.modules["strands_decider.modeling"] = modeling
    sys.modules["strands_decider.server"] = server


def main():
    captured = {}
    install_strands_stub(captured)
    from fastapi.testclient import TestClient
    import serve

    client = TestClient(serve.app)

    # /ping
    r = client.get("/ping")
    assert r.status_code == 200, f"/ping status {r.status_code}"

    # /invocations with a choice question carrying a null rubric (as the gate sends)
    req = {
        "state": "ship or hold?",
        "model": "strands-decider-2b",
        "questions": {
            "q1": {"type": "choice", "instructions": "pick",
                   "criteria": {"ship": None, "hold": "when risky"}},
        },
    }
    r = client.post("/invocations", content=json.dumps(req),
                    headers={"content-type": "application/json"})
    assert r.status_code == 200, f"/invocations status {r.status_code}"

    # inner saw /v1/systemone
    assert captured["path"] == "/v1/systemone", captured["path"]

    # null rubric rewritten to "" before reaching inner
    fwd = json.loads(captured["body"])
    crit = fwd["questions"]["q1"]["criteria"]
    assert crit["ship"] == "", f"null not blanked: {crit!r}"
    assert crit["hold"] == "when risky", crit

    # inner JSON returned verbatim
    out = r.json()
    assert out["answers"]["echo"]["model"] == "strands-decider-2b", out

    print("PASS: /ping 200; /invocations forwards to /v1/systemone; "
          "null criteria -> ''; inner JSON returned verbatim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
