"""System tray icon with status menu using pystray."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class TrayIcon:
    """System tray icon for the AnticLaw daemon.

    Provides menu items for status, force actions, and daemon control.
    Requires pystray and Pillow.
    """

    def __init__(
        self,
        home: Path,
        on_force_backup: object | None = None,
        on_force_sync: object | None = None,
        on_pause: object | None = None,
        on_resume: object | None = None,
        on_quit: object | None = None,
    ) -> None:
        self.home = home
        self._on_force_backup = on_force_backup
        self._on_force_sync = on_force_sync
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._on_quit = on_quit
        self._icon = None
        self._paused = False

    def start(self) -> None:
        """Start the system tray icon."""
        try:
            import pystray
        except ImportError as e:
            raise RuntimeError(
                f"pystray/Pillow not installed: {e}. "
                "Install with: pip install anticlaw[daemon]"
            ) from e

        image = self._create_icon_image()
        menu = self._build_menu(pystray)

        self._icon = pystray.Icon("anticlaw", image, "AnticLaw Daemon", menu)

        # Run in background thread
        thread = threading.Thread(target=self._icon.run, daemon=True)
        thread.start()
        log.info("Tray icon started")

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
        log.info("Tray icon stopped")

    def notify(self, title: str, message: str) -> None:
        """Show a desktop notification."""
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                log.debug("Notification failed", exc_info=True)

    def _create_icon_image(self):
        """Create a simple icon image (green circle)."""
        from PIL import Image, ImageDraw

        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # Green circle for active, yellow for paused
        color = (255, 200, 0) if self._paused else (0, 180, 0)
        draw.ellipse([4, 4, size - 4, size - 4], fill=color)
        # "A" letter in white
        draw.text((size // 2 - 8, size // 2 - 10), "A", fill=(255, 255, 255))
        return image

    def _build_menu(self, pystray):
        """Build the tray menu."""
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: self._status_text(),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Force Backup Now", self._do_force_backup),
            pystray.MenuItem("Force Sync Now", self._do_force_sync),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Data Folder", self._do_open_folder),
            pystray.MenuItem("View Logs", self._do_open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Resume Watching" if self._paused else "Pause Watching",
                self._do_toggle_pause,
            ),
            pystray.MenuItem("Quit", self._do_quit),
        )

    def _status_text(self) -> str:
        """Generate status text for the menu."""
        status = "Paused" if self._paused else "Watching"
        return f"{status}: {self.home}"

    def _do_force_backup(self, icon, item) -> None:
        if self._on_force_backup:
            threading.Thread(target=self._on_force_backup, daemon=True).start()

    def _do_force_sync(self, icon, item) -> None:
        if self._on_force_sync:
            threading.Thread(target=self._on_force_sync, daemon=True).start()

    def _do_open_folder(self, icon, item) -> None:
        """Open ACL_HOME in the system file manager."""
        import platform

        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(["explorer", str(self.home)])
            elif system == "Darwin":
                subprocess.Popen(["open", str(self.home)])
            else:
                subprocess.Popen(["xdg-open", str(self.home)])
        except Exception:
            log.warning("Failed to open folder", exc_info=True)

    def _do_open_logs(self, icon, item) -> None:
        """Open the cron.log in the default editor."""
        log_path = self.home / ".acl" / "cron.log"
        if not log_path.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")

        import platform

        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(["notepad", str(log_path)])
            elif system == "Darwin":
                subprocess.Popen(["open", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
        except Exception:
            log.warning("Failed to open logs", exc_info=True)

    def _do_toggle_pause(self, icon, item) -> None:
        self._paused = not self._paused
        if self._paused and self._on_pause:
            self._on_pause()
        elif not self._paused and self._on_resume:
            self._on_resume()
        # Update icon color
        icon.icon = self._create_icon_image()

    def _do_quit(self, icon, item) -> None:
        if self._on_quit:
            self._on_quit()
        icon.stop()
