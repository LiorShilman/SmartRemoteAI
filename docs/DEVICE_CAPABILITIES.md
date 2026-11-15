# Device capabilities

States: `unknown` (default), `supported`, `unsupported`. Only user observation moves a capability out of `unknown` for digits.

| Capability | HOT | LG |
|---|---|---|
| Navigation, Back, Home | unverified | unverified |
| Digits 0–9 | **unknown — must be tested** | n/a |
| Channel ± | unverified | n/a |
| Media keys | unverified | n/a |
| Volume / Mute | unverified | unverified |
| Inputs / Apps / Power off | n/a | unverified |
| Wake-on-LAN | n/a | unverified, off until tested |

Nothing here has been run against real hardware yet.

## B&W Zeppelin Pro Edition (speaker, `backend/app/services/zeppelin.py`)

Local HTTP API: `GET /api/getData?path=…&roles=value` and `GET /api/setData?path=…&role=value&value=<JSON>`.
The server exposes only the controls below (`/api/speaker/*`); there is no endpoint that reads or writes an arbitrary path.
Every write is read back, and success is reported only if the speaker reports the new value (it can answer HTTP 200 with an error body).

| Control | Path | Type | Status |
|---|---|---|---|
| Volume | `player:volume` | `i32_` | verified (23, 28 heard). UI/server range 0–100 assumed, full range not verified |
| Treble | `settings:/mediaPlayer/treble` | `double_` | verified (5, 6; syncs with the B&W app). Range −6…+6 assumed from the app |
| Ambient light on/off | `settings:/ui/ambientLightEnabled` | `bool_` | verified physically |
| Bass | `settings:/mediaPlayer/bass` | `double_` | verified in the lab 2026-11-15 (change heard). Range −6…+6 chosen by the user |
| Light brightness | `settings:/ui/ambientLightBrightness` | `i32_` | verified in the lab 2026-11-15 (change seen). Range 0–100 chosen by the user |
| Light colour | `settings:/ui/ambientLightRgb` | `formationDownlightRgb` | verified in the lab 2026-11-15 (change seen). Channels 0–255 |
| Loudness | `settings:/mediaPlayer/loudness` | `bool_` | on/off write + read-back verified 2026-11-15; no clear audible difference heard — labelled experimental in the UI |
| Mute | `settings:/mediaPlayer/mute` | `bool_` | verified by listening 2026-11-15 |
| Balance | `settings:/mediaPlayer/balance` | `double_` | 1 and 6 read back; no audible effect found. Card slider −6…+6 chosen by the user; which sign is left/right unknown, so no labels. Lab accepts any number |
| Source gain | `settings:/mediaPlayer/sourceGain` | — | the speaker rejects writes explicitly ("Setting is not modifiable") — no control, not exposed |
| Attenuation | `settings:/mediaPlayer/attenuation` | — | accepts writes but does not change the level — not used |
| 5-band EQ | `settings:/mediaPlayer/equalizer` | `eqBandList` | write + read-back verified 2026-11-15; effect heard by the user, not measured. Bands 60/250/1000/3500/12000 Hz; each band's min/max/step come from the speaker and are the only limits. Written as the whole list, other fields kept |
| EQ on/off | `settings:/mediaPlayer/equalizerOnOff` | `bool_` | read verified; write not verified — read-only on the EQ card, testable in the lab |

Address: `ZEPPELIN_HOST` (default `192.168.1.52`); the admin can change it in Settings, saved in the database.
The speaker stores ANY value it is sent (bass ±7 and brightness 101 were stored as sent), so reading back cannot reveal
its range; the ranges above are a choice, and whether values beyond them have an effect was not tested.

Test lab (Settings, admin only): tries bass/brightness/colour with saved originals and restore, and records what the user
observed. Kids-mode codes can read the speaker state but cannot change it.

## Automatic colour cycling (`backend/app/services/colorcycle.py`)

Runs on the server (continues with the browser closed), one task per speaker, started only by an explicit request — never at server start. Each step is an ordinary verified `ambientLightRgb` write, serialised with every other write; brightness is never written. Colours change in steps (the speaker's fade is untested). A manual colour, light off, an address change or server shutdown stops it, keeping the last colour. A disconnected speaker stops it with a message: no retries, no catch-up. Interval 3–3600 s (app limit), palette (2–12 colours) or random; settings are saved in the database.

## Personal profiles (`backend/app/services/profiles.py`)

Stored in SQLite (available from any browser). A profile holds the 5 EQ values, bass, treble, loudness, light colour and brightness, and the colour cycle (running, palette, interval, smooth); volume only when explicitly included. Never stored or changed: mute, balance, source gain, the light on/off switch. Saving reads fresh values (a partial capture is refused). Loading: undo snapshot first, cycle stopped, one verified write per setting, cycle restarted if the profile had it, then read back; every other speaker write is refused meanwhile. Each step reports its result and a partial load is reported as partial (and not marked as loaded). Never loaded automatically.
