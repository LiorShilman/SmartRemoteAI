"""Read-only crawl of the ui: menu tree + every node it references in other roots.
GET getRows/getData only. Never setData, never activate. Skips content browsing (streaming, files,
history) and stores no raw responses."""
import asyncio, json, re, sys, time
import httpx

HOST, OUT = sys.argv[1], sys.argv[2]
PAGE, CONC, TIMEOUT, MAX_NODES, MAX_DEPTH = 100, 3, 6.0, 1500, 7
SKIP = re.compile(r"^ui:/(playHistory|playlists|favorites|upnp|storage|files|spotify|audiogum|amazonmusic|tunein|"
                  r"sirius|vtuner|tidal|qobuz|pandora|airable\w*)", re.I)
MAC = re.compile(r"([0-9a-f]{2}[:_-]){5}[0-9a-f]{2}", re.I)
SENS = re.compile(r"pass|pwd|token|secret|psk|wpa|key|cert|credential|oauth|login|account|email|ssid|serial|uuid|cookie", re.I)
# current values worth reading (audio/power/info candidates), from the settings: catalogue
CANDIDATES = [
    "settings:/mediaPlayer/maxVolume", "settings:/mediaPlayer/defaultVolume", "settings:/mediaPlayer/defaultVolumeTimeout",
    "settings:/mediaPlayer/muteTimeout", "settings:/mediaPlayer/cuesFixedAttenuation", "settings:/mediaPlayer/duckingAttenuation",
    "settings:/mediaPlayer/attenuation", "settings:/mediaPlayer/playMode", "settings:/mediaPlayer/postprocessing",
    "settings:/system/maxIdleTime", "settings:/system/maxIdlePlayTime", "settings:/system/settings",
    "settings:/system/audioOutputDelay", "settings:/imx8AudioFramework/lipSyncConf",
    "settings:/bluetooth/autoPlayMode", "settings:/bluetooth/autoConnectMode", "settings:/bluetooth/aptxEnabled",
    "settings:/bluetooth/bluetoothPairingTimeout", "settings:/bluetooth/disablePairingOncePaired",
    "settings:/alerts/minimumVolume", "settings:/alerts/snoozeTime", "settings:/ui/displayBrightness",
    "settings:/ui/oobeLedEnabled", "settings:/ui/disabledPatternEvents", "settings:/ui/disabledEvents",
    "settings:/bw/zeppSpdifConnected", "settings:/version", "settings:/timezone", "settings:/deviceName",
    "settings:/fwupdate/enablePeriodicChecks", "settings:/avs/enableAudioCues", "settings:/mediaPlayer/micMute",
]
stats = {"getRows": 0, "getData": 0, "errors": 0}
errors = []

def scrub(s):
    return MAC.sub("<mac>", s) if isinstance(s, str) else s

async def get(c, sem, ep, params):
    async with sem:
        stats[ep] += 1
        try:
            r = await c.get(f"/api/{ep}", params=params)
        except httpx.HTTPError as e:
            return None, f"conn {type(e).__name__}"
        if r.status_code != 200:
            return None, f"http {r.status_code}"
        try:
            d = r.json()
        except ValueError:
            return None, "bad json"
        if isinstance(d, dict) and "error" in d:
            e = d["error"]
            return None, "body: " + (e.get("name", "") if isinstance(e, dict) else str(e))[:80]
        return d, None

def meta(d):
    keep = {k: d[k] for k in ("title", "type", "modifiable", "valueUnit", "edit", "defaultValue", "disabled") if k in d}
    v = d.get("value")
    if isinstance(v, dict) and "type" in v:
        keep["valueType"] = v["type"]
    return keep

async def rows(c, sem, path):
    out, start = [], 0
    while True:
        d, err = await get(c, sem, "getRows", {"path": path, "roles": "@all", "from": start, "to": start + PAGE - 1})
        if err:
            return out, err
        page = d.get("rows") or []
        out.extend(page)
        start += len(page)
        if not page or start >= (d.get("rowsCount") or 0):
            return out, None

async def main():
    sem = asyncio.Semaphore(CONC)
    nodes, seen, skipped = {}, {"ui:"}, []
    async with httpx.AsyncClient(base_url=f"http://{HOST}", timeout=TIMEOUT) as c:
        queue = [("ui:", 0)]
        while queue and len(nodes) < MAX_NODES:
            batch, queue = queue[:CONC * 2], queue[CONC * 2:]
            res = await asyncio.gather(*(rows(c, sem, p) for p, _ in batch))
            for (parent, depth), (children, err) in zip(batch, res):
                if err:
                    stats["errors"] += 1
                    errors.append({"path": scrub(parent), "op": "getRows", "error": err})
                for row in children:
                    p = row.get("path")
                    if not p or p in seen:
                        continue
                    seen.add(p)
                    n = {"path": p, "parent": parent, **meta(row)}
                    # keep the action/link role hints the menu exposes
                    for k in ("roles", "containerType", "context", "icon"):
                        if k in row:
                            n[k] = row[k]
                    nodes[p] = n
                    if SKIP.match(p):
                        skipped.append(p)
                        continue
                    if row.get("type") == "container" and depth + 1 < MAX_DEPTH:
                        queue.append((p, depth + 1))
        leaves = [p for p, n in nodes.items() if n.get("type") != "container" and not SKIP.match(p)]
        datas = await asyncio.gather(*(get(c, sem, "getData", {"path": p, "roles": "@all"}) for p in leaves))
        for p, (d, err) in zip(leaves, datas):
            if err:
                stats["errors"] += 1
                errors.append({"path": scrub(p), "op": "getData", "error": err})
                continue
            if isinstance(d, list):
                d = d[0] if d and isinstance(d[0], dict) else {}
            nodes[p].update(meta(d))
        cand = await asyncio.gather(*(get(c, sem, "getData", {"path": p, "roles": "@all"}) for p in CANDIDATES))
    current = {}
    for p, (d, err) in zip(CANDIDATES, cand):
        if err:
            current[p] = {"error": err}
        else:
            if isinstance(d, list):
                d = d[0] if d else {}
            current[p] = {"value": d.get("value"), **meta(d)}
    out_nodes = []
    for p, n in sorted(nodes.items()):
        n = dict(n)
        sensitive = bool(MAC.search(p) or SENS.search(p))
        n["path"], n["parent"] = scrub(p), scrub(n["parent"])
        if sensitive or MAC.search(json.dumps(n)):
            n.pop("defaultValue", None)
            if MAC.search(p):
                n["title"] = "<device>"
            n["redacted"] = True
        out_nodes.append(n)
    roots = sorted({n["path"].split(":")[0] + ":" for n in out_nodes})
    json.dump({"host": HOST, "root": "ui:", "crawledAt": time.strftime("%Y-%m-%d %H:%M:%S"),
               "nodeCount": len(out_nodes), "rootsSeen": roots, "skippedBranches": sorted(set(scrub(s) for s in skipped)),
               "stats": stats, "errors": errors, "candidateCurrentValues": current, "nodes": out_nodes},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("nodes", len(out_nodes), "roots", roots, stats, "errors", len(errors))

asyncio.run(main())
