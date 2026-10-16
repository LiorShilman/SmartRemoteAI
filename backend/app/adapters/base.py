from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import CapabilityState, Connection, ErrorCode


class AdapterError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DeviceAdapter(ABC):
    """One adapter instance per configured device. Commands arrive already validated."""

    kind: str

    def __init__(self, host: str | None):
        self.host = host

    @property
    @abstractmethod
    def connection(self) -> Connection: ...

    @property
    def capabilities(self) -> dict[str, CapabilityState]:
        return {}

    @abstractmethod
    async def pair_start(self) -> None: ...

    @abstractmethod
    async def pair_confirm(self, code: str) -> None: ...

    @abstractmethod
    async def execute(self, action: str, params: dict) -> None:
        """Raise AdapterError on failure. Returning means the command was transmitted."""

    async def selftest(self) -> dict:
        """Prove the device really answers (not just that we wrote to a socket). Returns
        {"ok": bool|None, "detail": str, "healed": bool}; ok=None means "cannot be verified"."""
        raise AdapterError(ErrorCode.UNSUPPORTED, "בדיקת חיבור לא זמינה למכשיר הזה.")

    async def pointer(self, dx: int, dy: int, scroll_dy: int, click: bool) -> None:
        """Mouse-style control. Only drivers with a real pointer protocol override this."""
        raise AdapterError(ErrorCode.UNSUPPORTED, "המכשיר הזה לא תומך בעכבר.")

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


class UnimplementedAdapter(DeviceAdapter):
    """Placeholder until the real adapter lands (Steps D/E). Never pretends to work."""

    def __init__(self, kind: str, host: str | None):
        super().__init__(host)
        self.kind = kind

    @property
    def connection(self) -> Connection:
        return "unpaired"

    async def pair_start(self) -> None:
        raise AdapterError(ErrorCode.UNSUPPORTED, "שליטה במכשיר הזה עדיין לא מומשה בשרת.")

    async def pair_confirm(self, code: str) -> None:
        raise AdapterError(ErrorCode.UNSUPPORTED, "שליטה במכשיר הזה עדיין לא מומשה בשרת.")

    async def execute(self, action: str, params: dict) -> None:
        raise AdapterError(ErrorCode.NOT_PAIRED, "המכשיר לא מצומד.")
