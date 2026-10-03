"""macOS desktop notification integration (PROJECT_GUIDE S5)."""

from __future__ import annotations

import platform
import shutil
import subprocess


def notify_macos(
    message: str,
    *,
    title: str = "AlphaBrief",
    subtitle: str | None = None,
    sound: str | None = None,
) -> bool:
    """Display a native macOS notification via osascript.

    Fails silently or returns False if not on macOS or if osascript fails,
    ensuring notifications never crash trading or operations.
    """
    if platform.system() != "Darwin":
        return False

    osascript = shutil.which("osascript")
    if not osascript:
        return False

    def _escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    script_parts = [
        f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    ]
    if subtitle:
        script_parts.append(f'subtitle "{_escape(subtitle)}"')
    if sound:
        script_parts.append(f'sound name "{_escape(sound)}"')

    script = " ".join(script_parts)

    try:
        proc = subprocess.run(
            [osascript, "-e", script],
            capture_output=True,
            timeout=5.0,
            check=False,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


__all__ = ["notify_macos"]
