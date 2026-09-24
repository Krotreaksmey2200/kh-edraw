"""Linux desktop integration helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

DESKTOP_ID = "edraw"
DESKTOP_FILENAME = f"{DESKTOP_ID}.desktop"


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _desktop_exec_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _desktop_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "applications"
    return Path.home() / ".local" / "share" / "applications"


def app_icon_path() -> Path | None:
    root = _resource_root()
    candidates = [
        root / "assets" / "iconEDraw.png",
        root / "docs" / "assets" / "iconEDraw.png",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def ensure_desktop_entry() -> None:
    """Create/update a user desktop entry so Linux shells can resolve eDraw's icon.

    PyInstaller one-dir executables do not carry a file-manager icon on Linux.
    The desktop entry gives GNOME/KDE a stable app id, icon and launch command.
    """
    if not sys.platform.startswith("linux"):
        return
    if not getattr(sys, "frozen", False):
        return

    exe = Path(sys.executable).resolve()
    icon = app_icon_path()

    desktop_dir = _desktop_dir()
    desktop_path = desktop_dir / DESKTOP_FILENAME

    content = (
        "[Desktop Entry]\n"
        f"Name=eDraw\n"
        f"Comment=eDraw — Digital Whiteboard & AI Exam Builder\n"
        f"Exec={_desktop_exec_quote(str(exe))}\n"
        f"Icon={_desktop_exec_quote(str(icon)) if icon else ''}\n"
        f"Type=Application\n"
        f"Categories=Education;Graphics;Utility;\n"
        f"Terminal=false\n"
        f"StartupWMClass=edraw\n"
    )

    try:
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(content, encoding="utf-8")
    except OSError:
        pass
