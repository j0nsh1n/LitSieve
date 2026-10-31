"""Laya sidecar: typed decisions for LitSieve over localhost HTTP.

Runs with Laya's own interpreter (it has torch and the checkpoint); LitSieve
never imports Laya. The worker is deliberately generic: LitSieve sends the
question (instructions + options) and the texts, and owns every option list and
threshold. Laya only decides.

    ~/.local/share/laya/bin/python tools/laya_worker.py --port 7880

Started by systemd socket activation (deploy/litsieve-laya.socket), it serves on
the inherited socket and, with --idle-exit, exits after that many idle seconds
to give its memory back; systemd keeps the port open and starts it again on the
next request. Run any other way, it binds the port itself and never idles out.

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
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_OFFLINE", "1")

MAX_BODY = 256 * 1024     # bytes
MAX_STATES = 64           # texts per request
MAX_OPTIONS = 16          # Laya's choice heads are calibrated up to 10; 13 topic areas still rank well
MAX_TEXT = 4000           # characters per text; Laya truncates to its own token budget anyway

_router = None
_relevance_agent = None
_relevance_checkpoint = None
_relevance_questions = None
_tag_checkpoint = None
_tag_agent = None
_lock = threading.Lock()  # one model, one GPU: decisions run one batch at a time
_device = "unloaded"
SD_LISTEN_FD = 3          # systemd hands the first activated socket over as fd 3


class Activity:
    """When the worker last served a request, and how many are in flight."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = 0
        self._last = time.monotonic()

    def begin(self) -> None:
        with self._lock:
            self._busy += 1
            self._last = time.monotonic()

    def end(self) -> None:
        with self._lock:
            self._busy -= 1
            self._last = time.monotonic()

    def idle_for(self, now: float) -> float:
        with self._lock:
            return 0.0 if self._busy else now - self._last


_activity = Activity()


def router():
    global _router, _device
    if _router is None:
        from laya import Router  # imported lazily: torch loads here
        _router = Router(preload=False, default="english")
        _router.predict(
            {"text": "This is a warmup sentence."},
            {"q": {"type": "noul", "instructions": "warm up"}},
        )
        try:
            import torch
            _device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            _device = "unknown"
    return _router


def tag_agent():
    global _tag_agent, _device
    if _tag_agent is None:
        from laya import load
        _tag_agent = load(_tag_checkpoint)
        try:
            import torch
            _device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            _device = "unknown"
    return _tag_agent


def relevance_agent():
    global _relevance_agent
    if _relevance_agent is None:
        from laya import load
        _relevance_agent = load(_relevance_checkpoint)
    return _relevance_agent


def preload() -> None:
    """Load every configured model before serving, so a wake-up is ready for the next search."""
    if _tag_checkpoint:
        tag_agent().predict_batch(
            [{"text": "This is a warmup sentence."}],
            {"pick": {"type": "choice", "instructions": "warm up", "criteria": {"a": "yes", "b": "no"}}},
            batch_size=1,
        )
    else:
        router()
    if _relevance_checkpoint:
        relevance_agent().predict_batch(["This is a warmup sentence."], _relevance_questions, batch_size=1)


def choice(instructions: str, options: dict, states: list, state_key: str = "text") -> list:
    q = {"pick": {"type": "choice", "instructions": instructions, "criteria": options}}
    with _lock:
        if _tag_checkpoint:
            res = tag_agent().predict_batch(
                [{"text": s[:MAX_TEXT]} for s in states], q, batch_size=len(states)
            )
        else:
            reqs = [{"state": {state_key: s[:MAX_TEXT]}, "questions": q} for s in states]
            res = router().predict_batch(reqs)
    out = []
    for r in res:
        a = r["answers"]["pick"]
        probs = {k: round(float(v), 4) for k, v in a["probabilities"].items()}
        out.append({"choice": a["choice"], "p": probs.get(a["choice"], 0.0), "probabilities": probs})
    return out


def configure_relevance(path: str) -> None:
    global _relevance_checkpoint, _relevance_questions
    with open(os.path.join(path, "questions.json"), encoding="utf-8") as f:
        questions = json.load(f)
    group = questions.get("group", {})
    if not isinstance(group, dict) or "answers" not in group.get("criteria", {}):
        raise ValueError("relevance checkpoint group must have an answers criterion")
    _relevance_checkpoint = path
    _relevance_questions = {"group": group}


def relevance(question: str, papers: list) -> list:
    states = []
    for paper in papers:
        title = " ".join(paper["title"].split()) or "(no title)"
        abstract = " ".join(paper["abstract"].split())
        lead = " ".join(re.split(r"(?<=[.!?])\s+", abstract)[:2])
        # No MAX_TEXT cut: the checkpoint was scored on uncut states; MAX_BODY bounds the request.
        states.append(f"Question: {question.strip()}\nTitle: {title}\nAbstract: {lead}")
    with _lock:
        rows = relevance_agent().predict_batch(states, _relevance_questions, batch_size=len(states))
    return [{"p_answers": float(row["answers"]["group"]["probabilities"]["answers"])} for row in rows]


def validate_relevance(body: dict) -> str | None:
    if not isinstance(body.get("question"), str) or not body["question"].strip():
        return "question must be a non-empty string"
    papers = body.get("papers")
    if not isinstance(papers, list) or not 1 <= len(papers) <= MAX_STATES:
        return f"papers must contain 1-{MAX_STATES} items"
    if not all(isinstance(p, dict) and isinstance(p.get("title"), str)
               and isinstance(p.get("abstract"), str) for p in papers):
        return "each paper must have string title and abstract"
    return None


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
    timeout = 30  # a connection that never sends a request would otherwise hold off --idle-exit forever

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # quiet; systemd journal gets errors only
        pass

    def handle_one_request(self):
        _activity.begin()
        try:
            super().handle_one_request()
        finally:
            _activity.end()

    def do_GET(self):
        if self.path == "/health":
            health = {"ok": True, "loaded": _router is not None or _tag_agent is not None, "device": _device,
                      "relevance_configured": _relevance_checkpoint is not None,
                      "relevance_loaded": _relevance_agent is not None}
            if _tag_checkpoint:
                health["tag_checkpoint"] = _tag_checkpoint
            self._send(200, health)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/v1/choice", "/v1/relevance"):
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "body missing or too large"})
        try:
            body = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        body = body if isinstance(body, dict) else {}
        if self.path == "/v1/relevance" and _relevance_checkpoint is None:
            return self._send(404, {"error": "relevance not configured"})
        err = (validate_relevance(body) if self.path == "/v1/relevance" else validate(body))
        if err:
            return self._send(400, {"error": err})
        t = time.time()
        try:
            if self.path == "/v1/relevance":
                results = relevance(body["question"], body["papers"])
            else:
                results = choice(body["instructions"], body["options"], body["states"], body.get("state_key") or "text")
        except Exception as exc:  # report, never crash the worker
            return self._send(500, {"error": f"{type(exc).__name__}: {exc}"[:300]})
        self._send(200, {"results": results, "ms": round((time.time() - t) * 1000, 1)})


def socket_activated() -> bool:
    return os.environ.get("LISTEN_PID") == str(os.getpid()) and int(os.environ.get("LISTEN_FDS") or 0) >= 1


def exit_when_idle(srv: ThreadingHTTPServer, seconds: float) -> None:
    while _activity.idle_for(time.monotonic()) < seconds:
        time.sleep(min(seconds / 4, 5.0))
    srv.shutdown()


def main():
    global _tag_checkpoint
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("LAYA_WORKER_PORT", "7880")))
    ap.add_argument("--no-preload", action="store_true", help="load the model on the first request")
    ap.add_argument("--idle-exit", type=float, default=0, metavar="SECONDS",
                    help="when socket-activated, exit after this long without a request (0: never)")
    ap.add_argument("--relevance-checkpoint", metavar="PATH")
    ap.add_argument("--tag-checkpoint", metavar="PATH")
    args = ap.parse_args()
    _tag_checkpoint = args.tag_checkpoint
    if args.relevance_checkpoint:
        configure_relevance(args.relevance_checkpoint)
    if not args.no_preload:
        preload()
    activated = socket_activated()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler, bind_and_activate=not activated)
    if activated:
        srv.socket.close()
        srv.socket = socket.socket(fileno=SD_LISTEN_FD)
    idle_exit = args.idle_exit if activated else 0
    if idle_exit > 0:
        threading.Thread(target=exit_when_idle, args=(srv, idle_exit), daemon=True).start()
    where = "socket from systemd" if activated else f"127.0.0.1:{args.port}"
    idle = f", exits after {idle_exit:g}s idle" if idle_exit > 0 else ""
    print(f"laya-worker on {where} (device {_device}{idle})", flush=True)
    srv.serve_forever()
    srv.server_close()


if __name__ == "__main__":
    main()
