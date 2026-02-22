"""IPC for CLI-to-daemon communication via Unix socket / Named pipe."""

from __future__ import annotations

import json
import logging
import platform
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


def ipc_path(home: Path) -> Path:
    """Return the IPC socket/pipe path."""
    if _IS_WINDOWS:
        return Path(r"\\.\pipe\anticlaw-daemon")
    return home / ".acl" / "daemon.sock"


class IPCServer:
    """IPC server that listens for commands from the CLI.

    On Unix: Unix domain socket.
    On Windows: Named pipe (emulated via socket on localhost).
    """

    def __init__(self, home: Path, handler: object | None = None) -> None:
        self.home = home
        self._handler = handler  # callable(command: dict) -> dict
        self._server_socket = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the IPC server in a background thread."""
        import socket

        sock_path = ipc_path(self.home)

        if _IS_WINDOWS:
            # Use TCP on localhost for Windows
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("127.0.0.1", _get_port(self.home)))
            self._server_socket.settimeout(1.0)
            self._server_socket.listen(5)
        else:
            # Unix domain socket
            if sock_path.exists():
                sock_path.unlink()
            sock_path.parent.mkdir(parents=True, exist_ok=True)
            self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_socket.settimeout(1.0)
            self._server_socket.bind(str(sock_path))
            self._server_socket.listen(5)

        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        log.info("IPC server started")

    def stop(self) -> None:
        """Stop the IPC server."""
        self._running = False
        if self._server_socket is not None:
            self._server_socket.close()
            self._server_socket = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

        # Cleanup socket file
        sock_path = ipc_path(self.home)
        if not _IS_WINDOWS and sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        log.info("IPC server stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _accept_loop(self) -> None:
        """Accept incoming connections."""
        import socket

        while self._running:
            try:
                conn, _ = self._server_socket.accept()
                threading.Thread(
                    target=self._handle_connection, args=(conn,), daemon=True,
                ).start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    log.warning("IPC accept error", exc_info=True)
                break

    def _handle_connection(self, conn) -> None:
        """Handle a single IPC connection."""
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            if not data:
                return

            command = json.loads(data.decode("utf-8").strip())
            log.debug("IPC received: %s", command)

            if self._handler is not None:
                response = self._handler(command)
            else:
                response = {"status": "ok", "message": "no handler registered"}

            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))

        except Exception:
            log.warning("IPC connection error", exc_info=True)
            try:
                error_resp = json.dumps({"status": "error", "message": "internal error"})
                conn.sendall((error_resp + "\n").encode("utf-8"))
            except OSError:
                pass
        finally:
            conn.close()


def ipc_send(home: Path, command: dict, timeout: float = 5.0) -> dict:
    """Send a command to the running daemon and return the response.

    Used by CLI commands to communicate with the daemon.
    """
    import socket

    sock_path = ipc_path(home)

    try:
        if _IS_WINDOWS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(("127.0.0.1", _get_port(home)))
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(str(sock_path))

        sock.sendall((json.dumps(command) + "\n").encode("utf-8"))
        sock.shutdown(1)  # SHUT_WR — signal end of sending

        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        sock.close()
        return json.loads(data.decode("utf-8").strip())

    except (OSError, json.JSONDecodeError, ConnectionRefusedError) as e:
        return {"status": "error", "message": f"Cannot connect to daemon: {e}"}


def is_daemon_running(home: Path) -> bool:
    """Check if the daemon is running by attempting IPC ping."""
    resp = ipc_send(home, {"action": "ping"}, timeout=2.0)
    return resp.get("status") == "ok"


def _get_port(home: Path) -> int:
    """Derive a deterministic port number from the home path (Windows only)."""
    return 19384 + (hash(str(home)) % 1000)
