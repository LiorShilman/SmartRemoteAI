# HOT pairing checklist (Step D) — physical device

Not yet run on real hardware. Do these in order and note the result of each.

1. Backend running **without** mock: `.\.venv\Scripts\python run.py` (note the ACCESS_TOKEN). Frontend: Live mode + token.
2. Settings → "סרוק רשת" (mDNS). If the box is not listed: add it by IP (find it in the router or the box's network settings).
3. Pair → "התחל צימוד". A code should appear on the TV within a few seconds. Result: ____
   - Error "לא ניתן להתחבר": check IP, box is on, same network/VLAN, Windows Firewall allows Python on Private networks.
4. Enter the code → "הצימוד הושלם", device shows "מחובר". Result: ____
5. HOT remote tab: D-pad, OK, Home, Back, Menu — each reacts on screen? Result: ____
6. Channel ± / Play-Pause / Rewind / FF — which react? Result: ____
7. Volume/mute keys sent to HOT — does the box or TV react? (Prefer LG for volume.) Result: ____
8. Restart the backend. Device returns to "מחובר" without re-pairing. Result: ____
9. Turn the box off/on: status goes "מנותק" and recovers by itself. Result: ____
10. Digits (Settings → בדיקת ספרות): send 1, 2, 12 (and with OK). Mark the outcome yourself. Result: ____

If step 3/4 fails with an auth/pairing error, record the exact message: it means the box may not accept a third-party
Android TV Remote v2 client, and the fallback is navigation + Channel ± only.

Diagnostics (no secrets): `GET /api/devices/{id}/diagnostics`, or Settings → export logs.
Certificates are stored server-side in `backend/data/certs/` — never commit or share that folder.
