"""Kids mode: what a restricted access code may do. Enforced on the server for every request, not in the UI.

A policy lives on an access token. The master (admin) code is never restricted.
"""
from __future__ import annotations

from datetime import datetime

from app.models.policy import AppName, Policy  # noqa: F401  (re-exported)
from app.models.schemas import Action

APP_LABEL = {"youtube": "YouTube", "netflix": "Netflix", "spotify": "Spotify"}

# While the daily limit is used up only these still work: turning the volume down and switching the screen off.
OVER_LIMIT_OK = {Action.VOLUME_DOWN, Action.MUTE, Action.POWER_OFF}


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def window_open(p: dict, now: datetime, extra_min: int = 0) -> bool:
    """Inside [start, end + granted extra minutes]. Extra time never opens the window before `start`."""
    cur = now.hour * 60 + now.minute
    return _minutes(p["start"]) <= cur < _minutes(p["end"]) + extra_min


def over_limit(p: dict, used_min: float, extra_min: int = 0) -> bool:
    limit = p.get("daily_limit_min")
    return bool(limit) and used_min >= limit + extra_min


def remaining_min(p: dict, used_min: float, extra_min: int = 0) -> int | None:
    limit = p.get("daily_limit_min")
    return None if not limit else max(0, int(limit + extra_min - used_min))


def deny_reason(p: dict, action: Action, params: dict, now: datetime, used_min: float, extra_min: int) -> str | None:
    """A Hebrew reason when this restricted code may NOT do this, else None."""
    if not window_open(p, now, extra_min):
        end = p["end"]
        return f"מחוץ לשעות המותרות ({p['start']}–{end}). אפשר לבקש עוד זמן."
    if over_limit(p, used_min, extra_min):
        if action in OVER_LIMIT_OK:
            return None
        return "הגעת למכסת הזמן היומית. אפשר לבקש עוד זמן."
    if action in (Action.POWER_OFF, Action.POWER_ON) and not p.get("can_power_off"):
        return "אין הרשאה לכבות או להדליק את המכשיר."
    if action in (Action.LAUNCH_APP, Action.SEARCH) and params.get("app") not in p.get("apps", []):
        name = APP_LABEL.get(str(params.get("app")), str(params.get("app")))
        return f"האפליקציה {name} לא מורשית."
    return None


def schedule_denied(p: dict) -> str | None:
    return None if p.get("can_schedule") else "אין הרשאה לתזמן או לבטל פעולות מתוזמנות."
