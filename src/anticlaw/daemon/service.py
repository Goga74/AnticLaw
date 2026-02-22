"""Platform-specific service registration for the daemon."""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def get_pid_path(home: Path) -> Path:
    """Return the PID file path."""
    return home / ".acl" / "daemon.pid"


def write_pid(home: Path) -> None:
    """Write current process PID to the PID file."""
    pid_path = get_pid_path(home)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def read_pid(home: Path) -> int | None:
    """Read the daemon PID from the PID file. Returns None if not found."""
    pid_path = get_pid_path(home)
    if not pid_path.exists():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def remove_pid(home: Path) -> None:
    """Remove the PID file."""
    pid_path = get_pid_path(home)
    if pid_path.exists():
        with contextlib.suppress(OSError):
            pid_path.unlink()


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except (subprocess.SubprocessError, OSError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False


def install_service(home: Path) -> str:
    """Install the daemon as a system service. Returns status message."""
    system = platform.system()

    if system == "Windows":
        return _install_windows(home)
    elif system == "Darwin":
        return _install_macos(home)
    else:
        return _install_linux(home)


def uninstall_service(home: Path) -> str:
    """Uninstall the daemon system service. Returns status message."""
    system = platform.system()

    if system == "Windows":
        return _uninstall_windows(home)
    elif system == "Darwin":
        return _uninstall_macos(home)
    else:
        return _uninstall_linux(home)


# --- Windows ---

def _install_windows(home: Path) -> str:
    """Create a Windows startup shortcut using pythonw.exe."""
    startup_dir = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )
    if not startup_dir.exists():
        return f"Startup directory not found: {startup_dir}"

    # Create a .bat file in Startup
    python_exe = sys.executable
    # Use pythonw.exe for windowless execution
    pythonw = python_exe.replace("python.exe", "pythonw.exe")
    if not Path(pythonw).exists():
        pythonw = python_exe

    bat_path = startup_dir / "anticlaw-daemon.bat"
    bat_content = (
        f'@echo off\nstart /B "" "{pythonw}"'
        f' -m anticlaw.cli.main daemon start --home "{home}"\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")

    return f"Created startup script: {bat_path}"


def _uninstall_windows(home: Path) -> str:
    startup_dir = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    )
    bat_path = startup_dir / "anticlaw-daemon.bat"
    if bat_path.exists():
        bat_path.unlink()
        return f"Removed startup script: {bat_path}"
    return "No startup script found"


# --- macOS ---

_LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.anticlaw.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>-m</string>
        <string>anticlaw.cli.main</string>
        <string>daemon</string>
        <string>start</string>
        <string>--home</string>
        <string>{home}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""


def _install_macos(home: Path) -> str:
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.anticlaw.daemon.plist"

    log_path = home / ".acl" / "daemon.log"
    content = _LAUNCHD_PLIST.format(
        python_exe=sys.executable,
        home=home,
        log_path=log_path,
    )
    plist_path.write_text(content, encoding="utf-8")

    subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    return f"Created launchd plist: {plist_path}"


def _uninstall_macos(home: Path) -> str:
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.anticlaw.daemon.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink()
        return f"Removed launchd plist: {plist_path}"
    return "No launchd plist found"


# --- Linux ---

_SYSTEMD_UNIT = """\
[Unit]
Description=AnticLaw Daemon
After=network.target

[Service]
Type=simple
ExecStart={python_exe} -m anticlaw.cli.main daemon start --home {home}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _install_linux(home: Path) -> str:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "anticlaw-daemon.service"

    content = _SYSTEMD_UNIT.format(python_exe=sys.executable, home=home)
    unit_path.write_text(content, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "anticlaw-daemon"], check=False)
    return f"Created systemd unit: {unit_path}"


def _uninstall_linux(home: Path) -> str:
    unit_path = Path.home() / ".config" / "systemd" / "user" / "anticlaw-daemon.service"
    if unit_path.exists():
        subprocess.run(["systemctl", "--user", "disable", "anticlaw-daemon"], check=False)
        subprocess.run(["systemctl", "--user", "stop", "anticlaw-daemon"], check=False)
        unit_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        return f"Removed systemd unit: {unit_path}"
    return "No systemd unit found"
