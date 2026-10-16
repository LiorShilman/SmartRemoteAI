"""Friendly names for what a device reports as its foreground app (used for screen-time statistics).

`None` means "idle / home screen": it is not counted as screen time.
"""
from __future__ import annotations

import re

NAMES = {
    # Android TV packages
    "com.netflix.ninja": "Netflix",
    "com.google.android.youtube.tv": "YouTube",
    "com.spotify.tv.android": "Spotify",
    "il.net.hot.hot": "שידורי HOT",
    # LG webOS app ids
    "netflix": "Netflix",
    "youtube.leanback.v4": "YouTube",
    "spotify-beehive": "Spotify",
    "com.webos.app.livetv": "שידורי טלוויזיה",
}
IDLE = {
    "com.google.android.tvlauncher", "com.google.android.apps.tv.launcherx", "com.google.android.leanbacklauncher",
    "com.android.vending", "com.android.tv.settings", "com.webos.app.home", "com.webos.app.discovery",
}
_HDMI = re.compile(r"^com\.webos\.app\.hdmi(\d)$")


def friendly(app_id: str | None) -> str | None:
    """Name to show for an app id, or None when the device is idle / on its home screen."""
    if not app_id or app_id in IDLE:
        return None
    if app_id in NAMES:
        return NAMES[app_id]
    if (m := _HDMI.match(app_id)):
        return f"HDMI {m.group(1)}"
    return ".".join(app_id.split(".")[-2:])  # unknown package: its last two parts, e.g. "disney.plus"
