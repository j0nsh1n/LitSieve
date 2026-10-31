"""The Laya sidecar's idle exit: started by systemd socket activation it frees its
memory after --idle-exit seconds without a request; started any other way it
stays up. Runs the real worker with --no-preload, so no model or torch loads."""
from __future__ import annotations

import configparser
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import types

import pytest
import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKER = [sys.executable, str(REPO / "tools" / "laya_worker.py"), "--no-preload"]
ACTIVATE = shutil.which("systemd-socket-activate")
needs_activate = pytest.mark.skipif(not ACTIVATE, reason="systemd-socket-activate not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(args, env=None):
    proc = subprocess.Popen(args, cwd=REPO, env={**os.environ, **(env or {})},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc


def _health(port):
    return requests.get(f"http://127.0.0.1:{port}/health", timeout=5).json()


def _wait_up(port, proc):
    for _ in range(100):
        try:
            return _health(port)
        except requests.ConnectionError:
            assert proc.poll() is None, "worker died while starting"
            time.sleep(0.05)
    raise AssertionError("worker never answered /health")


@pytest.fixture
def worker():
    procs = []

    def start(*extra, activated=True, env=None):
        port = _free_port()
        if activated:
            args = [ACTIVATE, "-l", f"127.0.0.1:{port}", *WORKER, "--port", str(port), *extra]
        else:
            args = [*WORKER, "--port", str(port), *extra]
        proc = _start(args, env)
        procs.append(proc)
        return port, proc

    yield start
    for p in procs:
        if p.poll() is None:
            p.kill()
            p.wait()


@needs_activate
def test_socket_activated_worker_exits_cleanly_after_idling(worker):
    port, proc = worker("--idle-exit", "1")
    assert _wait_up(port, proc)["loaded"] is False
    assert proc.wait(timeout=10) == 0


@needs_activate
def test_each_request_restarts_the_idle_clock(worker):
    port, proc = worker("--idle-exit", "1.5")
    _wait_up(port, proc)
    for _ in range(6):
        time.sleep(0.5)
        assert _health(port)["ok"]
    assert proc.poll() is None, "exited while still being asked"
    assert proc.wait(timeout=10) == 0


@needs_activate
def test_a_request_in_flight_holds_off_the_exit(worker):
    port, proc = worker("--idle-exit", "1")
    _wait_up(port, proc)
    body = b"not json"
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(b"POST /v1/choice HTTP/1.0\r\nContent-Length: %d\r\n\r\n" % len(body))
        time.sleep(2.5)
        assert proc.poll() is None, "exited mid-request"
        s.sendall(body)
        reply = s.makefile("rb").read()
    time.sleep(0.6)
    assert proc.poll() is None, "the idle clock did not restart when the request ended"
    assert reply.startswith(b"HTTP/1.0 400")
    assert json.loads(reply.split(b"\r\n\r\n", 1)[1]) == {"error": "invalid JSON"}
    assert proc.wait(timeout=10) == 0


def test_without_socket_activation_it_binds_its_port_and_never_idles_out(worker):
    port, proc = worker("--idle-exit", "1", activated=False)
    _wait_up(port, proc)
    time.sleep(2.5)
    assert proc.poll() is None
    assert _health(port)["ok"]


def test_a_stray_listen_fds_from_another_process_is_ignored(worker):
    port, proc = worker("--idle-exit", "1", activated=False, env={"LISTEN_PID": "1", "LISTEN_FDS": "1"})
    _wait_up(port, proc)
    time.sleep(2.5)
    assert proc.poll() is None


def test_bad_requests_are_refused_before_the_model_loads(worker):
    port, proc = worker(activated=False)
    _wait_up(port, proc)
    r = requests.post(f"http://127.0.0.1:{port}/v1/choice", json={"instructions": "", "options": {}, "states": []}, timeout=5)
    assert r.status_code == 400
    assert _health(port)["loaded"] is False


def test_health_reports_configured_tag_checkpoint_without_loading(worker):
    port, proc = worker("--tag-checkpoint", "/checkpoint", activated=False)
    health = _wait_up(port, proc)
    assert health["tag_checkpoint"] == "/checkpoint"
    assert health["loaded"] is False


def _unit(name):
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(REPO / "deploy" / name)
    return cp


def test_router_keeps_the_english_default(monkeypatch):
    created = []
    warmup = []

    class FakeRouter:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def predict(self, state, questions):
            warmup.append((state, questions))
            return {}

    fake_laya = types.ModuleType("laya")
    fake_laya.Router = FakeRouter
    monkeypatch.setitem(sys.modules, "laya", fake_laya)
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    spec = importlib.util.spec_from_file_location(
        "laya_worker_router_test", REPO / "tools" / "laya_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod._router = None
    mod.router()
    assert created == [{"preload": False, "default": "english"}]
    assert warmup[0][0]["text"] == "This is a warmup sentence."


def test_systemd_units_start_laya_on_demand_and_let_it_idle_out():
    sock, svc = _unit("litsieve-laya.socket"), _unit("litsieve-laya.service")
    assert sock["Socket"]["ListenStream"] == "127.0.0.1:7880"
    assert sock["Install"]["WantedBy"] == "sockets.target"
    assert "--idle-exit 300" in svc["Service"]["ExecStart"]
    assert svc["Unit"]["Requires"] == "litsieve-laya.socket"
    assert not svc.has_section("Install"), "an enabled service would load Laya at login and hold the memory"


def test_tag_checkpoint_uses_panel_input_and_never_loads_router(monkeypatch):
    spec = importlib.util.spec_from_file_location("laya_worker_tag_test", REPO / "tools" / "laya_worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []

    class FakeAgent:
        def predict_batch(self, states, questions, batch_size):
            calls.append((states, questions, batch_size))
            return [{"answers": {"pick": {"choice": "one", "probabilities": {"one": 0.87654, "two": 0.12346}}}}]

    fake = types.ModuleType("laya")
    fake.load = lambda path: calls.append(path) or FakeAgent()
    monkeypatch.setitem(sys.modules, "laya", fake)
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(mod, "router", lambda: pytest.fail("base router loaded"))
    mod._tag_checkpoint = "/checkpoint"
    result = mod.choice("Question?", {"one": "First", "two": "Second"}, ["a" * 4001], "other")
    assert calls == ["/checkpoint", ([{"text": "a" * 4000}], {"pick": {"type": "choice", "instructions": "Question?", "criteria": {"one": "First", "two": "Second"}}}, 1)]
    assert result == [{"choice": "one", "p": 0.8765, "probabilities": {"one": 0.8765, "two": 0.1235}}]
    assert mod._device == "cpu"
