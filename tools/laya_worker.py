"""Laya sidecar: typed decisions for LitSieve over localhost HTTP.

Runs with Laya's own interpreter (it has torch and the checkpoint); LitSieve
never imports Laya. The worker is deliberately generic: LitSieve sends the
question (instructions + options) and the texts, and owns every option list and
threshold. Laya only decides.

    ~/.local/share/laya/bin/python tools/laya_worker.py --port 7880

Endpoints (127.0.0.1 only):
    GET  /health             -> {"ok": true, "device": "cuda", "loaded": true}
    POST /v1/choice          {"instructions": str, "options": {id: description},
                              "states": [str, ...], "state_key": "text"}
                          -> {"results": [{"choice": id, "p": float,
                                           "probabilities": {id: float}}], "ms": float}
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_OFFLINE", "1")

MAX_BODY = 256 * 1024     # bytes
MAX_STATES = 64           # texts per request
MAX_OPTIONS = 16          # Laya's choice heads are calibrated up to 10; 13 topic areas still rank well
MAX_TEXT = 4000           # characters per text; Laya truncates to its own token budget anyway

_router = None
_lock = threading.Lock()  # one model, one GPU: decisions run one batch at a time
_device = "unloaded"


def router():
    global _router, _device
    if _router is None:
        from laya import Router  # imported lazily: torch loads here
        _router = Router(preload=False)
        _router.predict({"text": "warm up"}, {"q": {"type": "noul", "instructions": "warm up"}})
        try:
            import torch
            _device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            _device = "unknown"
    return _router


def choice(instructions: str, options: dict, states: list, state_key: str = "text") -> list:
    q = {"pick": {"type": "choice", "instructions": instructions, "criteria": options}}
    reqs = [{"state": {state_key: s[:MAX_TEXT]}, "questions": q} for s in states]
    with _lock:
        res = router().predict_batch(reqs)
    out = []
    for r in res:
        a = r["answers"]["pick"]
        probs = {k: round(float(v), 4) for k, v in a["probabilities"].items()}
        out.append({"choice": a["choice"], "p": probs.get(a["choice"], 0.0), "probabilities": probs})
    return out


def validate(body: dict) -> str | None:
    if not isinstance(body.get("instructions"), str) or not body["instructions"].strip():
        return "instructions must be a non-empty string"
    opts = body.get("options")
    if not isinstance(opts, dict) or not 2 <= len(opts) <= MAX_OPTIONS or not all(isinstance(v, str) for v in opts.values()):
        return f"options must map 2-{MAX_OPTIONS} ids to descriptions"
    states = body.get("states")
    if not isinstance(states, list) or not 1 <= len(states) <= MAX_STATES or not all(isinstance(s, str) for s in states):
        return f"states must be 1-{MAX_STATES} strings"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "laya-worker/1"

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # quiet; systemd journal gets errors only
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "loaded": _router is not None, "device": _device})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/choice":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "body missing or too large"})
        try:
            body = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        err = validate(body if isinstance(body, dict) else {})
        if err:
            return self._send(400, {"error": err})
        t = time.time()
        try:
            results = choice(body["instructions"], body["options"], body["states"], body.get("state_key") or "text")
        except Exception as exc:  # report, never crash the worker
            return self._send(500, {"error": f"{type(exc).__name__}: {exc}"[:300]})
        self._send(200, {"results": results, "ms": round((time.time() - t) * 1000, 1)})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("LAYA_WORKER_PORT", "7880")))
    ap.add_argument("--no-preload", action="store_true", help="load the model on the first request")
    args = ap.parse_args()
    if not args.no_preload:
        router()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"laya-worker on 127.0.0.1:{args.port} (device {_device})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
