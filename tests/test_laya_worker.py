"""The Laya sidecar's idle exit: started by systemd socket activation it frees its
memory after --idle-exit seconds without a request; started any other way it
stays up. Runs the real worker with --no-preload, so no model or torch loads."""
from __future__ import annotations

import configparser
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

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


def _unit(name):
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(REPO / "deploy" / name)
    return cp


def test_systemd_units_start_laya_on_demand_and_let_it_idle_out():
    sock, svc = _unit("litsieve-laya.socket"), _unit("litsieve-laya.service")
    assert sock["Socket"]["ListenStream"] == "127.0.0.1:7880"
    assert sock["Install"]["WantedBy"] == "sockets.target"
    assert "--idle-exit 300" in svc["Service"]["ExecStart"]
    assert svc["Unit"]["Requires"] == "litsieve-laya.socket"
    assert not svc.has_section("Install"), "an enabled service would load Laya at login and hold the memory"
