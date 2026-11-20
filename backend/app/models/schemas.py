"""Strict request/response schemas. Mirrors frontend/src/types."""
from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.policy import Policy
from app.services.speaker_voice import SpeakerOp, check_speaker

DeviceKind = Literal["hot", "lg"]
StepTarget = Literal["hot", "lg", "speaker"]  # voice steps and schedules may also address the speaker
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
    TEXT = "text"      # type text into the focused field of the device
    SEARCH = "search"  # open an app straight on its search results
    DIGITS = "digits"  # whole channel number as one server-side timed key sequence


# Allowlists: the UI never sends free-form strings to a device.
HOT_KEYS = frozenset(
    {"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER", "BACK", "HOME", "MENU",
     "SETTINGS", "GUIDE", "INFO", "MEDIA_PLAY_PAUSE", "MEDIA_REWIND", "MEDIA_FAST_FORWARD",
     "CHANNEL_UP", "CHANNEL_DOWN", "PAGE_UP", "PAGE_DOWN", "LAST_CHANNEL", "DEL", "ENTER", *(f"KEYCODE_{d}" for d in range(10))}
)
LG_KEYS = frozenset({"DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER", "BACK", "HOME",
                     "MENU", "QMENU", "EXIT", "INFO", "GUIDE", "INPUT_HUB", "RED", "GREEN", "YELLOW", "BLUE", "DEL"})
KEYS_BY_KIND: dict[str, frozenset[str]] = {"hot": HOT_KEYS, "lg": LG_KEYS}
APPS = frozenset({"youtube", "netflix", "spotify"})  # logical names; each adapter maps them to its own app ids
LG_APPS = APPS
INPUT_RE = re.compile(r"^HDMI_[1-4]$")
DIGITS_RE = re.compile(r"^\d{1,4}$")
LG_ONLY_ACTIONS = frozenset({Action.POWER_OFF, Action.POWER_ON, Action.SET_INPUT})
MAX_SCHEDULE_S = 12 * 3600
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT, MAX_QUERY = 120, 80
IPV4_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$")


def check_params(action: Action, p: dict) -> None:
    """Kind-independent parameter rules. Raises ValueError."""
    if action is Action.KEY_PRESS and not isinstance(p.get("key"), str):
        raise ValueError("key_press requires params.key")
    if action is Action.SET_INPUT and not INPUT_RE.match(str(p.get("input", ""))):
        raise ValueError("set_input requires params.input like HDMI_1")
    if action is Action.LAUNCH_APP and p.get("app") not in LG_APPS:
        raise ValueError("launch_app requires a known params.app")
    if action is Action.TEXT:
        t = p.get("text")
        if not isinstance(t, str) or not 1 <= len(t) <= MAX_TEXT or CONTROL_CHARS.search(t):
            raise ValueError(f"text must be 1-{MAX_TEXT} printable characters")
        if not isinstance(p.get("submit", False), bool):
            raise ValueError("submit must be boolean")
    if action is Action.SEARCH:
        q = p.get("query")
        if p.get("app") not in APPS:
            raise ValueError("search requires a known params.app")
        if not isinstance(q, str) or not q.strip() or len(q) > MAX_QUERY or CONTROL_CHARS.search(q):
            raise ValueError(f"query must be 1-{MAX_QUERY} printable characters")
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
    target: StepTarget
    action: Action | SpeakerOp
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    label: str
    delay_seconds: int = 0  # >0 means "schedule on the server", never a browser timer


class IntentOut(BaseModel):
    steps: list[IntentStepOut]
    unrecognized: list[str]
    provider: str


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: StepTarget
    action: Action | SpeakerOp
    params: dict[str, str | int | bool] = Field(default_factory=dict)
    delay_seconds: int = Field(ge=1, le=MAX_SCHEDULE_S)
    label: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def _check(self) -> ScheduleCreate:
        if (self.target == "speaker") != isinstance(self.action, SpeakerOp):
            raise ValueError("speaker steps go to the speaker only")
        if isinstance(self.action, SpeakerOp):
            check_speaker(self.action, self.params)
            return self
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
    target: StepTarget
    action: Action | SpeakerOp
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
    policy: Policy | None = None  # kids mode; None = a normal (unrestricted, non-admin) code

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
    policy: dict | None = None


class TokenCreated(TokenOut):
    token: str  # the only time the secret is ever returned


class AuditOut(BaseModel):
    id: int
    at: float
    ip: str
    who: str
    event: str
    detail: str


class TokenPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Policy | None = None  # null removes the restrictions


class TimeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: Literal[15, 30, 60, 120]


class TimeDecide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    minutes: int | None = Field(default=None, ge=5, le=240)  # a parent may grant less/more than was asked


class TimeRequestOut(BaseModel):
    id: str
    token_id: str
    token_name: str
    minutes: int
    status: Literal["pending", "approved", "denied"]
    created_at: float
    decided_at: float | None = None
    granted_minutes: int = 0


class UsageDay(BaseModel):
    day: str
    total_min: int
    apps: dict[str, int]


class UsageOut(BaseModel):
    today_min: int
    days: list[UsageDay]


class MeOut(BaseModel):
    kind: Literal["admin", "device"]
    name: str
    # kids mode (only for restricted codes)
    policy: dict | None = None
    used_min: int | None = None
    remaining_min: int | None = None
    extra_min: int = 0
    window_open: bool | None = None
    request_status: Literal["pending", "approved", "denied"] | None = None
    # admin only
    pending_requests: int | None = None


class TtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    voice: Literal["hila", "avri"] = "hila"

    @field_validator("text")
    @classmethod
    def _printable(cls, v: str) -> str:
        if CONTROL_CHARS.search(v) or not v.strip():
            raise ValueError("text must be printable")
        return v


class HealthOut(BaseModel):
    ok: bool = True
    version: str


# ---- B&W Zeppelin speaker: one schema per verified control. There is no "path" field anywhere, by design.
class SpeakerVolume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(strict=True, ge=0, le=50)  # speaker units (player:volume declares 0..50), shown as is


class SpeakerTreble(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(strict=True, ge=-10, le=10)  # dB; the node declares -10..+10 step 0.5

    @field_validator("value")
    @classmethod
    def _half_steps(cls, v: float) -> float:
        if abs(v * 2 - round(v * 2)) > 1e-9:
            raise ValueError("value must be a multiple of 0.5")
        return v


class SpeakerLight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class SpeakerBass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(strict=True, ge=-10, le=10)  # dB; the node declares -10..+10 step 0.5

    @field_validator("value")
    @classmethod
    def _half_steps(cls, v: float) -> float:
        if abs(v * 2 - round(v * 2)) > 1e-9:
            raise ValueError("value must be a multiple of 0.5")
        return v


class SpeakerBrightness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(strict=True, ge=0, le=100)


class SpeakerRgb(BaseModel):
    model_config = ConfigDict(extra="forbid")
    red: int = Field(strict=True, ge=0, le=255)
    green: int = Field(strict=True, ge=0, le=255)
    blue: int = Field(strict=True, ge=0, le=255)


class SpeakerMute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class SpeakerLoudness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class SpeakerBalance(BaseModel):
    """-6..+6, chosen by the user (the speaker stores any value, so it cannot tell its range). Which sign is left/right
    is unknown. The lab still accepts any finite number for tests outside this range."""
    model_config = ConfigDict(extra="forbid")
    value: float = Field(strict=True, ge=-6, le=6)


class SpeakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        return check_host(v)


class SpeakerStandbyOption(BaseModel):
    seconds: int
    title: str                     # as the speaker names it ("30 minutes")


class SpeakerStandby(BaseModel):
    seconds: int                   # current value; may be one the list does not contain (factory 1200)
    options: list[SpeakerStandbyOption]


class SpeakerStandbySet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: int = Field(strict=True, ge=0, le=86400)  # must also be in the speaker's list (checked against it)


class SpeakerSource(BaseModel):
    id: str                        # "airplay", "bluetooth", "spdif"…
    title: str
    active: bool                   # currently playing from it
    plugged: bool                  # connected / available according to the speaker
    available: bool                # the speaker's menu does not mark it disabled


class SpeakerSources(BaseModel):
    sources: list[SpeakerSource]


class SpeakerBtDevice(BaseModel):
    id: str                        # opaque, server-made; the Bluetooth address is never sent to the browser
    name: str
    roles: list[Literal["input", "speaker"]]


class SpeakerBluetooth(BaseModel):
    name: str                      # the name phones see ("Living Room")
    discoverable: bool             # visible / accepting a new pairing right now
    pairable: bool
    connected_device: str | None = None
    paired: list[str] = []
    devices: list[SpeakerBtDevice] | None = None  # paired devices as the speaker's own menu lists them; None = unreadable
    pairing_seconds: int | None = None            # how long the speaker keeps pairing open (its own setting, read only)
    sent: bool | None = None       # pairing request only: False = was already visible, nothing sent
    unpaired: str | None = None    # unpair request only: the name of the device that was removed


class SpeakerStepRequest(BaseModel):
    """One step of the closed voice vocabulary (see services/speaker_voice). No paths, no raw values beyond its ranges."""
    model_config = ConfigDict(extra="forbid")
    op: SpeakerOp
    params: dict[str, str | int | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> SpeakerStepRequest:
        check_speaker(self.op, self.params)
        return self


class SpeakerUnpair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[0-9a-f]{12}$")


class SpeakerState(BaseModel):
    host: str
    reachable: bool
    volume: int | None = None
    treble: float | None = None
    light: bool | None = None
    bass: float | None = None
    brightness: int | None = None
    rgb: dict[str, int] | None = None
    mute: bool | None = None
    loudness: bool | None = None
    balance: float | None = None
    power: str | None = None         # read only, as reported: "online", "networkStandby", ...
    power_reason: str | None = None  # e.g. "idleTimer" (the automatic standby)
    errors: dict[str, str] = Field(default_factory=dict)  # per control, when that one could not be read


# ---- Zeppelin test lab (admin): unverified controls. Only the value TYPE is checked, never a guessed range: what the
# speaker accepts is exactly what the lab is for finding out. (RGB channels 0..255 are the colour format itself.)
I32_MIN, I32_MAX = -(2**31), 2**31 - 1
LabControl = Literal["bass", "brightness", "rgb", "eq_enabled", "loudness", "balance"]


class LabBass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(strict=True, allow_inf_nan=False)


class LabBrightness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(strict=True, ge=I32_MIN, le=I32_MAX)


class LabRgb(BaseModel):
    model_config = ConfigDict(extra="forbid")
    red: int = Field(strict=True, ge=0, le=255)
    green: int = Field(strict=True, ge=0, le=255)
    blue: int = Field(strict=True, ge=0, le=255)


class LabBool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool = Field(strict=True)


class LabObservation(BaseModel):
    """What the user saw/heard on the speaker after the last test of this control."""
    model_config = ConfigDict(extra="forbid")
    control: LabControl
    result: Literal["changed", "no_change", "unsure"]
    note: str | None = Field(default=None, max_length=120)


# ---- Zeppelin 5-band equalizer. Range and step come from the speaker per band and are checked on the server against
# what the speaker reports at write time, not against constants here.
class EqBandValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    band: str = Field(min_length=1, max_length=8, pattern=r"^\d{1,6}$")
    value: float = Field(strict=True, allow_inf_nan=False)


class EqWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bands: list[EqBandValue] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _unique(self) -> "EqWrite":
        if len({b.band for b in self.bands}) != len(self.bands):
            raise ValueError("duplicate band")
        return self


class EqBand(BaseModel):
    band: str
    min: float
    max: float
    step: float
    value: float


class EqOut(BaseModel):
    bands: list[EqBand] | None = None
    enabled: bool | None = None  # equalizerOnOff, read only here until its write is verified
    errors: dict[str, str] = Field(default_factory=dict)


# ---- Zeppelin automatic colour cycling (run on the server). Interval limits are the app's, to never flood the speaker.
class CycleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_s: int = Field(strict=True, ge=3, le=3600)
    mode: Literal["palette", "random"]
    palette: list[SpeakerRgb] = Field(default_factory=list, max_length=12)
    smooth: bool = Field(default=False, strict=True)  # intermediate colours, written by the server (not a speaker fade)


# ---- Zeppelin personal profiles
class ProfileName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v or CONTROL_CHARS.search(v):
            raise ValueError("name must be 1-40 printable characters")
        return v


class ProfileCreate(ProfileName):
    include_volume: bool = Field(default=False, strict=True)  # volume only when explicitly chosen
