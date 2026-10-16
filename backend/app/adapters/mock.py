from __future__ import annotations

from app.adapters.base import AdapterError, DeviceAdapter
from app.models.schemas import CapabilityState, Connection, ErrorCode

MOCK_PAIR_CODE = "123456"


class MockAdapter(DeviceAdapter):
    """In-memory device for tests and local development. Never talks to hardware."""

    def __init__(self, kind: str, host: str | None):
        super().__init__(host)
        self.kind = kind
        self.paired = False
        self.sent: list[tuple[str, dict]] = []
        self.fail_with: ErrorCode | None = None  # test hook

    @property
    def connection(self) -> Connection:
        return "connected" if self.paired else "unpaired"

    @property
    def capabilities(self) -> dict[str, CapabilityState]:
        if self.kind == "hot":
            return {"nav": "supported", "channel_step": "unknown", "digits": "unknown", "media": "unknown", "apps": "unknown"}
        return {"nav": "unknown", "volume": "unknown", "mute": "unknown",
                "power_off": "unknown", "inputs": "unknown", "apps": "unknown", "wol": "unknown"}

    async def pair_start(self) -> None:
        return None

    async def pair_confirm(self, code: str) -> None:
        if self.kind == "hot" and code != MOCK_PAIR_CODE:
            raise AdapterError(ErrorCode.DENIED, "קוד הצימוד שגוי.")
        self.paired = True

    async def selftest(self) -> dict:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        return {"ok": getattr(self, "selftest_ok", True), "healed": False, "detail": "בדיקה מדומה."}

    async def pointer(self, dx: int, dy: int, scroll_dy: int, click: bool) -> None:
        if self.kind != "lg":
            raise AdapterError(ErrorCode.UNSUPPORTED, "המכשיר הזה לא תומך בעכבר.")
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        self.pointer_events = getattr(self, "pointer_events", []) + [(dx, dy, scroll_dy, click)]

    async def execute(self, action: str, params: dict) -> None:
        if not self.paired:
            raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
        if self.fail_with:
            raise AdapterError(self.fail_with, "כשל מדומה.")
        self.sent.append((action, dict(params)))
