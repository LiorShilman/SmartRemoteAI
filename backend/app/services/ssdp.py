"""SSDP discovery for LG webOS TVs (they answer the webos-second-screen search target)."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass

ST = "urn:lge-com:service:webos-second-screen:1"
MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
    f"MX: 2\r\nST: {ST}\r\n\r\n"
).encode()


@dataclass(frozen=True)
class FoundTv:
    host: str
    server: str


def _local_ipv4s() -> list[str]:
    ips = {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    return [ip for ip in ips if ipaddress.ip_address(ip).is_private]


def _scan(timeout: float) -> list[FoundTv]:
    found: dict[str, FoundTv] = {}
    socks = []
    for ip in _local_ipv4s() or ["0.0.0.0"]:  # one socket per NIC so the right network is searched
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((ip, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.settimeout(0.3)
            for _ in range(2):
                s.sendto(MSEARCH, ("239.255.255.250", 1900))
            socks.append(s)
        except OSError:
            s.close()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for s in socks:
            try:
                data, (addr, _) = s.recvfrom(4096)
            except (TimeoutError, OSError):
                continue
            text = data.decode("utf-8", "ignore")
            if ST.lower() not in text.lower() or not ipaddress.ip_address(addr).is_private:
                continue
            server = next((ln.split(":", 1)[1].strip() for ln in text.split("\r\n") if ln.lower().startswith("server:")), "")
            found[addr] = FoundTv(host=addr, server=server)
    for s in socks:
        s.close()
    return list(found.values())


async def discover_lg(timeout: float = 3.0) -> list[FoundTv]:
    return await asyncio.to_thread(_scan, timeout)
