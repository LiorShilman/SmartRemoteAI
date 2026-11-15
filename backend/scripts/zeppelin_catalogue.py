"""Read-only crawl of the Zeppelin node API. GET getRows/getData only; never setData.

Writes a filtered catalogue: no raw responses, current values only for known audio/light controls.
"""
import asyncio, json, re, sys, time
import httpx

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.52"
OUT = sys.argv[2]
ROOT = "settings:"
PAGE = 100            # 'to' is inclusive
CONC = 3
TIMEOUT = 6.0

VALUE_ALLOW = {        # known audio + lighting controls: keep the current value
    "player:volume",
    "settings:/mediaPlayer/treble", "settings:/mediaPlayer/bass", "settings:/mediaPlayer/mute",
    "settings:/mediaPlayer/loudness", "settings:/mediaPlayer/balance",
    "settings:/mediaPlayer/equalizerOnOff", "settings:/mediaPlayer/equalizer",
    "settings:/mediaPlayer/sourceGain",
    "settings:/ui/ambientLightEnabled", "settings:/ui/ambientLightBrightness", "settings:/ui/ambientLightRgb",
}
SENSITIVE = re.compile(
    r"pass|pwd|token|secret|psk|wpa|wep|key|cert|credential|auth|login|account|user|email|"
    r"ssid|bssid|wifi|wlan|network|ip|mac|serial|uuid|oauth|session|cookie|pair|bond|"
    r"spotify|tidal|deezer|qobuz|airable|cloud|gcast|cast|homekit",
    re.I)
MAC = re.compile(r"([0-9a-f]{2}[:_-]){5}[0-9a-f]{2}", re.I)

def scrub_path(p: str) -> str:
    return MAC.sub("<mac>", p)

def is_sensitive(path: str, title: str = "") -> bool:
    return bool(SENSITIVE.search(path) or SENSITIVE.search(title or "") or MAC.search(path))

stats = {"getRows": 0, "getData": 0, "http_err": 0, "json_err": 0, "body_err": 0, "timeout": 0}
errors: list[dict] = []

async def get(c, sem, endpoint, params):
    async with sem:
        stats[endpoint] += 1
        for attempt in (1, 2):
            try:
                r = await c.get(f"/api/{endpoint}", params=params)
            except httpx.TimeoutException:
                stats["timeout"] += 1
                if attempt == 2:
                    return None, "timeout"
                await asyncio.sleep(0.5)
                continue
            except httpx.HTTPError as e:
                stats["http_err"] += 1
                return None, f"conn:{type(e).__name__}"
            if r.status_code != 200:
                stats["http_err"] += 1
                return None, f"http {r.status_code}"
            try:
                d = r.json()
            except ValueError:
                stats["json_err"] += 1
                return None, "bad json"
            if isinstance(d, dict) and "error" in d:
                stats["body_err"] += 1
                e = d["error"]
                return None, "body error: " + (str(e.get("message") or e.get("name") or e)[:80] if isinstance(e, dict) else str(e)[:80])
            return d, None
        return None, "unreachable"

def meta(d: dict) -> dict:
    keep = {}
    for k in ("title", "type", "modifiable", "valueUnit", "edit", "defaultValue", "disabled", "requestable"):
        if k in d:
            keep[k] = d[k]
    v = d.get("value")
    if isinstance(v, dict) and "type" in v:
        keep["valueType"] = v["type"]
    return keep

async def rows(c, sem, path):
    out, start, total = [], 0, None
    while True:
        d, err = await get(c, sem, "getRows", {"path": path, "roles": "@all", "from": start, "to": start + PAGE - 1})
        if err:
            return out, err, total
        page = d.get("rows") or []
        total = d.get("rowsCount", total)
        out.extend(page)
        start += len(page)
        if not page or total is None or start >= total:
            return out, None, total

async def main():
    sem = asyncio.Semaphore(CONC)
    seen, nodes = set(), {}
    async with httpx.AsyncClient(base_url=f"http://{HOST}", timeout=TIMEOUT) as c:
        queue = [ROOT]
        seen.add(ROOT)
        while queue:
            batch, queue = queue[:CONC * 2], queue[CONC * 2:]
            results = await asyncio.gather(*(rows(c, sem, p) for p in batch))
            for parent, (children, err, total) in zip(batch, results):
                if err:
                    errors.append({"path": scrub_path(parent), "op": "getRows", "error": err})
                if parent in nodes:
                    nodes[parent]["childCount"] = total
                for row in children:
                    p = row.get("path")
                    if not p or p in seen:
                        continue
                    seen.add(p)
                    nodes[p] = {"path": p, **meta(row)}
                    if row.get("type") == "container":
                        queue.append(p)
        # complete leaf details with getData
        leaves = [p for p, n in nodes.items() if n.get("type") != "container"]
        datas = await asyncio.gather(*(get(c, sem, "getData", {"path": p, "roles": "@all"}) for p in leaves))
        values = {}
        for p, (d, err) in zip(leaves, datas):
            if err:
                errors.append({"path": scrub_path(p), "op": "getData", "error": err})
                continue
            if isinstance(d, list):
                d = d[0] if d and isinstance(d[0], dict) else {}
            nodes[p].update({k: v for k, v in meta(d).items() if k not in nodes[p] or k in ("edit", "defaultValue", "valueUnit", "modifiable")})
            if p in VALUE_ALLOW:
                values[p] = d.get("value")
        # player:volume separately (outside settings:)
        vol, verr = await get(c, sem, "getData", {"path": "player:volume", "roles": "@all"})

    catalogue = []
    for p, n in sorted(nodes.items()):
        n = dict(n)
        if is_sensitive(p, n.get("title", "")):
            n.pop("defaultValue", None)
            if isinstance(n.get("edit"), dict):
                n["edit"] = {k: v for k, v in n["edit"].items() if k in ("type", "min", "max", "step")}
            n["redacted"] = True
        n["path"] = scrub_path(p)
        if p in values:
            n["currentValue"] = values[p]
        catalogue.append(n)
    out = {
        "host": HOST, "root": ROOT, "crawledAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "nodeCount": len(catalogue), "stats": stats, "errors": errors,
        "playerVolume": None if verr else {"path": "player:volume", **meta(vol), "currentValue": vol.get("value")},
        "playerVolumeError": verr,
        "nodes": catalogue,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"nodes={len(catalogue)} stats={stats} errors={len(errors)}")

asyncio.run(main())
