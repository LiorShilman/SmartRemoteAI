"""LAN discovery via mDNS. Android TV Remote v2 advertises _androidtvremote2._tcp."""
from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass

from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

SERVICE = "_androidtvremote2._tcp.local."


@dataclass(frozen=True)
class Found:
    name: str
    host: str


async def discover_android_tv(timeout: float = 3.0) -> list[Found]:
    found: dict[str, Found] = {}
    tasks: set[asyncio.Task] = set()
    azc = AsyncZeroconf()

    async def resolve(name: str) -> None:
        info = AsyncServiceInfo(SERVICE, name)
        if await info.async_request(azc.zeroconf, 2000):
            for addr in info.parsed_addresses():
                ip = ipaddress.ip_address(addr)
                if ip.version == 4 and ip.is_private:
                    label = name.removesuffix("." + SERVICE) or name
                    found[addr] = Found(name=label, host=addr)

    def on_change(zeroconf, service_type, name, state_change):  # noqa: ANN001
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            t = asyncio.ensure_future(resolve(name))
            tasks.add(t)
            t.add_done_callback(tasks.discard)

    browser = AsyncServiceBrowser(azc.zeroconf, SERVICE, handlers=[on_change])
    try:
        await asyncio.sleep(timeout)
        if tasks:
            await asyncio.wait(tasks, timeout=3)
    finally:
        await browser.async_cancel()
        await azc.async_close()
    return list(found.values())
