"""Strict request/response schemas. Mirrors frontend/src/types."""
from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DeviceKind = Literal["hot", "lg"]
Connection = Literal["connected", "disconnected", "unpaired"]
Role = Literal["tv", "box"]
CapabilityState = Literal["unknown", "supported", "unsupported"]


class ErrorCode(StrEnum):
    NOT_PAIRED = "NOT_PAIRED"
    NOT_CONNECTED = "NOT_CONNECTED"
    UNSUPPORTED = "UNSUPPORTED"
    TIMEOUT = "TIMEOUT"
    DENIED = "DENIED"
    INVALID_COMMAND = "INVALID_COMMAND"


class Action(StrEnum):
    KEY_PRESS = "key_press"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    POWER_OFF = "power_off"
    POWER_ON = "power_on"
    SET_INPUT = "set_input"
    LAUNCH_APP = "launch_app"
    CHANNEL_STEP = "channel_step"  # emulated: current channel +/-1, sent as digits
    CHANNEL_LAST = "channel_last"  # emulated: back to the previous channel, sent as digits
    DIGITS = "digits"  # whole channel number as one server-side timed key sequence


# Allowlists: the UI never sends free-form strings to a device.
HOT_KEYS = frozenset(
    {"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER", "BACK", "HOME", "MENU",
     "SETTINGS", "GUIDE", "INFO", "MEDIA_PLAY_PAUSE", "MEDIA_REWIND", "MEDIA_FAST_FORWARD",
     "CHANNEL_UP", "CHANNEL_DOWN", "PAGE_UP", "PAGE_DOWN", "LAST_CHANNEL", *(f"KEYCODE_{d}" for d in range(10))}
)
LG_KEYS = frozenset({"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER", "BACK", "HOME",
                     "MENU", "QMENU", "EXIT", "INFO", "GUIDE", "INPUT_HUB", "RED", "GREEN", "YELLOW", "BLUE"})
KEYS_BY_KIND: dict[str, frozenset[str]] = {"hot": HOT_KEYS, "lg": LG_KEYS}
APPS = frozenset({"youtube", "netflix", "spotify"})  # logical names; each adapter maps them to its own app ids
LG_APPS = APPS
INPUT_RE = re.compile(r"^HDMI_[1-4]$")
DIGITS_RE = re.compile(r"^\d{1,4}$")
LG_ONLY_ACTIONS = frozenset({Action.POWER_OFF, Action.POWER_ON, Action.SET_INPUT})
MAX_SCHEDULE_S = 12 * 3600
IPV4_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")


def check_params(action: Action, p: dict) -> None:
    """Kind-independent parameter rules. Raises ValueError."""
    if action is Action.KEY_PRESS and not isinstance(p.get("key"), str):
        raise ValueError("key_press requires params.key")
    if action is Action.SET_INPUT and not INPUT_RE.match(str(p.get("input", ""))):
        raise ValueError("set_input requires params.input like HDMI_1")
    if action is Action.LAUNCH_APP and p.get("app") not in LG_APPS:
        raise ValueError("launch_app requires a known params.app")
    if action is Action.CHANNEL_STEP and p.get("delta") not in (1, -1):
        raise ValueError("delta must be 1 or -1")
    if action in (Action.DIGITS, Action.CHANNEL_STEP, Action.CHANNEL_LAST):
        if action is Action.DIGITS and not DIGITS_RE.match(str(p.get("digits", ""))):
            raise ValueError("digits requires 1-4 digits")
        d = p.get("delay_ms", 350)
        if isinstance(d, bool) or not isinstance(d, int) or not 50 <= d <= 2000:
            raise ValueError("delay_ms must be 50..2000")
        if not isinstance(p.get("enter", False), bool):
            raise ValueError("enter must be boolean")


def check_kind(kind: str, action: Action, p: dict) -> str | None:
    """Rules that depend on the device kind. Returns an error string or None."""
    if action in LG_ONLY_ACTIONS and kind != "lg":
        return "הפעולה נתמכת רק ב-LG."
    if action in (Action.DIGITS, Action.CHANNEL_STEP, Action.CHANNEL_LAST) and kind != "hot":
        return "ספרות נתמכות רק ב-HOT."
    if action is Action.KEY_PRESS and p.get("key") not in KEYS_BY_KIND[kind]:
        return "מקש לא מורשה."
    return None


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=64)
    action: Action
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    request_id: str = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def _check_params(self) -> CommandRequest:
        check_params(self.action, self.params)
        return self


class CommandResponse(BaseModel):
    # "sent" = transmitted to the device. Never means the device visibly reacted.
    status: Literal["sent", "duplicate"]
    request_id: str


def check_host(v: str) -> str:
    """A device address must be a private LAN IPv4: the server never talks to arbitrary hosts."""
    v = v.strip()
    if not IPV4_RE.match(v):
        raise ValueError("host must be an IPv4 address")
    ip = ipaddress.ip_address(v)
    if not ip.is_private or ip.is_loopback or ip.is_unspecified:
        raise ValueError("host must be a private LAN address")
    return v


class NewDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DeviceKind  # connection driver: "lg" = LG webOS, "hot" = Android TV Remote v2 (any Android TV / Google TV)
    host: str
    role: Role | None = None
    name: str | None = Field(default=None, max_length=40)

    @field_validator("host")
    @classmethod
    def _ipv4(cls, v: str) -> str:
        return check_host(v)


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=40)
    role: Role | None = None
    host: str | None = None

    @field_validator("host")
    @classmethod
    def _host(cls, v: str | None) -> str | None:
        return check_host(v) if v is not None else None


class PointerEvent(BaseModel):
    """One batched touchpad update. Bounded so a client cannot flood or fling the pointer."""
    model_config = ConfigDict(extra="forbid")
    dx: int = Field(default=0, ge=-200, le=200)
    dy: int = Field(default=0, ge=-200, le=200)
    scroll_dy: int = Field(default=0, ge=-30, le=30)
    click: bool = False


class PairConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(default="", max_length=16)


class DeviceOut(BaseModel):
    id: str
    kind: DeviceKind
    role: Role = "box"
    name: str
    host: str | None = None
    connection: Connection
    capabilities: dict[str, CapabilityState]
    last_error: str | None = None
    # Channel numbers this server last typed into the box. NOT read from the box: a physical remote makes it stale.
    channel: str | None = None
    previous_channel: str | None = None


class IntentParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    volume_target: DeviceKind = "lg"


class IntentStepOut(BaseModel):
    target: DeviceKind
    action: Action
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    label: str
    delay_seconds: int = 0  # >0 means "schedule on the server", never a browser timer


class IntentOut(BaseModel):
    steps: list[IntentStepOut]
    unrecognized: list[str]
    provider: str


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: DeviceKind
    action: Action
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    delay_seconds: int = Field(ge=1, le=MAX_SCHEDULE_S)
    label: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def _check(self) -> ScheduleCreate:
        check_params(self.action, self.params)
        if (e := check_kind(self.target, self.action, self.params)):
            raise ValueError(e)
        return self


class ScheduleClear(BaseModel):
    """ids given: delete exactly those (a still-pending one is cancelled and removed, so it never runs).
    ids omitted: tidy up, i.e. delete everything that is no longer pending."""
    model_config = ConfigDict(extra="forbid")
    ids: list[str] | None = Field(default=None, max_length=50)


class ScheduleOut(BaseModel):
    id: str
    run_at: float
    target: DeviceKind
    action: Action
    params: dict[str, str | int | bool]
    label: str
    status: Literal["pending", "done", "failed", "missed", "cancelled"]
    error: str | None = None


class ChannelSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(pattern=r"^\d{1,4}$")


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class TokenClear(BaseModel):
    """ids given: remove exactly those that are already revoked. ids omitted: remove every revoked token."""
    model_config = ConfigDict(extra="forbid")
    ids: list[str] | None = Field(default=None, max_length=50)


class TokenOut(BaseModel):
    id: str
    name: str
    prefix: str  # first characters only, to recognise a token in the list. Never the secret.
    created_at: float
    last_used_at: float | None = None
    last_ip: str | None = None
    revoked: bool = False


class TokenCreated(TokenOut):
    token: str  # the only time the secret is ever returned


class AuditOut(BaseModel):
    id: int
    at: float
    ip: str
    who: str
    event: str
    detail: str


class MeOut(BaseModel):
    kind: Literal["admin", "device"]
    name: str


class HealthOut(BaseModel):
    ok: bool = True
    version: str
