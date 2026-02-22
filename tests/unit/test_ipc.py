"""Tests for anticlaw.daemon.ipc — IPC server and client."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from anticlaw.daemon.ipc import IPCServer, ipc_path, ipc_send, is_daemon_running


class TestIPCPath:
    def test_unix_path(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", False)
        p = ipc_path(tmp_path)
        assert p == tmp_path / ".acl" / "daemon.sock"

    def test_windows_path(self, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)
        p = ipc_path(Path("/fake"))
        assert "pipe" in str(p).lower()


class TestIPCRoundTrip:
    def test_ping_pong(self, tmp_path: Path, monkeypatch):
        """Full round-trip: start server, send command, receive response."""
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)

        responses = {}

        def handler(command):
            action = command.get("action", "")
            if action == "ping":
                return {"status": "ok", "message": "pong"}
            return {"status": "error", "message": "unknown"}

        server = IPCServer(tmp_path, handler=handler)
        server.start()

        try:
            # Give server time to start
            time.sleep(0.3)

            # Send a ping
            resp = ipc_send(tmp_path, {"action": "ping"}, timeout=3.0)
            assert resp["status"] == "ok"
            assert resp["message"] == "pong"
        finally:
            server.stop()

    def test_unknown_action(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)

        def handler(command):
            return {"status": "error", "message": f"unknown: {command.get('action')}"}

        server = IPCServer(tmp_path, handler=handler)
        server.start()

        try:
            time.sleep(0.3)
            resp = ipc_send(tmp_path, {"action": "bad-action"}, timeout=3.0)
            assert resp["status"] == "error"
        finally:
            server.stop()

    def test_multiple_requests(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)
        counter = {"n": 0}

        def handler(command):
            counter["n"] += 1
            return {"status": "ok", "count": counter["n"]}

        server = IPCServer(tmp_path, handler=handler)
        server.start()

        try:
            time.sleep(0.3)

            for i in range(3):
                resp = ipc_send(tmp_path, {"action": "count"}, timeout=3.0)
                assert resp["status"] == "ok"
                assert resp["count"] == i + 1
        finally:
            server.stop()


class TestIsDaemonRunning:
    def test_not_running_when_no_server(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)
        assert is_daemon_running(tmp_path) is False


class TestIPCSendNoServer:
    def test_returns_error_when_no_server(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("anticlaw.daemon.ipc._IS_WINDOWS", True)
        resp = ipc_send(tmp_path, {"action": "ping"}, timeout=1.0)
        assert resp["status"] == "error"
        assert "Cannot connect" in resp["message"]
