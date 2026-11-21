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
| Volume | `player:volume` | `i32_` | verified (23, 28 heard). Range **0–50 step 1, declared by the speaker** (`edit` metadata; `volumeMap` has 51 entries −120…0 dB); values above 50 are rejected. Server accepts 0–50 and the UI shows the same 0–50 (user's choice). Windows/phones over Bluetooth show it as 0–100, hence their 2% jumps |
| Treble | `settings:/mediaPlayer/treble` | `double_` | verified (5, 6, 7 written and read back; 11 came back clamped to 10; syncs with the B&W app). Range −10…+10 step 0.5 as declared by the node; audible effect beyond 6 not verified yet |
| Ambient light on/off | `settings:/ui/ambientLightEnabled` | `bool_` | verified physically |
| Bass | `settings:/mediaPlayer/bass` | `double_` | verified in the lab 2026-11-15 (change heard). Range −10…+10 step 0.5 from the node's metadata only; audible effect beyond 6 not verified |
| Standby timeout | `settings:/system/maxIdleTime` | `i32_` (seconds) | verified 2026-11-16 (1200 → 1800 written and read back, restored to 1200). Choices only from the speaker's own list `settings:/system/maxIdleTimeValues` (off, 5, 10, 15, 30 min); factory value 1200 is not in that list and is shown as is |
| Power state | `powermanager:target` | `powerTarget` (read only) | read 2026-11-16: `networkStandby` (reason `idleTimer`) after the automatic standby, `online` (reason `userActivity`) when woken. With network standby the speaker keeps answering while off, so the card shows **כבוי** from this, not from reachability |
| Restart | `powermanager:goReboot` | action (POST setData, role `activate`) | found 2026-11-20 (`getData roles=@all` → `type: action`); `settings:/ui/disabledReboot` = false. **Not yet sent from the app.** The physical reset button (short press) restarted the speaker the same day and kept pairings and settings. Success only when the speaker stops answering within 20 s and answers again within 180 s; nothing is sent if `disabledReboot` is true |
| Bluetooth unpair | `bluetooth:devices/<address>/unpair` (action, as listed under the device in `ui:/bluetooth`) | activate | verified 2026-11-16 (one user-approved unpair of a stale phone record: the device left the paired sections). Only devices in section1 "Inputs" / section2 "Speakers" are offered; section3 "New devices" (nearby, not paired) is ignored — unpair there returns HTTP 500. Ids sent to the browser are opaque (HMAC), never addresses. `bluetooth:state` `pairedDevices` keeps stale/duplicate names after an unpair, so the list comes from the menu |
| Bluetooth pairing window | `settings:/bluetooth/bluetoothPairingTimeout` | `i32_` (read only) | 300 s; the UI counts down from it only when it opened pairing itself |
| Audio sources | `ui:/bw` → `bw:<source>` | `bwAudioInput` (read only) | read 2026-11-16: per source `active`/`plugged`; the menu's `disabled` matches `plugged=false`. Shown on the card; switching (activating `bw:<source>`) not verified, not offered |
| Light brightness | `settings:/ui/ambientLightBrightness` | `i32_` | verified in the lab 2026-11-15 (change seen). Range 0–100 chosen by the user |
| Light colour | `settings:/ui/ambientLightRgb` | `formationDownlightRgb` | verified in the lab 2026-11-15 (change seen). Channels 0–255 |
| Loudness | `settings:/mediaPlayer/loudness` | `bool_` | on/off write + read-back verified 2026-11-15. Effect heard by the user when playing over Wi-Fi, taking a few seconds to apply (not heard earlier over Bluetooth from the PC). Back on the main card |
| Mute | `settings:/mediaPlayer/mute` | `bool_` | verified by listening 2026-11-15 |
| Balance | `settings:/mediaPlayer/balance` | `double_` | 1 and 6 read back; no audible effect found. Card slider −6…+6 chosen by the user; which sign is left/right unknown, so no labels. Lab accepts any number |
| Source gain | `settings:/mediaPlayer/sourceGain` | — | the speaker rejects writes explicitly ("Setting is not modifiable") — no control, not exposed |
| Attenuation | `settings:/mediaPlayer/attenuation` | — | accepts writes but does not change the level — not used |
| 5-band EQ | `settings:/mediaPlayer/equalizer` | `eqBandList` | write + read-back verified 2026-11-15; effect heard by the user, not measured. Bands 60/250/1000/3500/12000 Hz; each band's min/max/step come from the speaker and are the only limits. Written as the whole list, other fields kept |
| EQ on/off | `settings:/mediaPlayer/equalizerOnOff` | `bool_` | read verified; write not verified — read-only on the EQ card, testable in the lab |

Address: `ZEPPELIN_HOST` (default `192.168.1.52`); the admin can change it in Settings, saved in the database.
The speaker stores ANY value it is sent (bass ±7 and brightness 101 were stored as sent), so reading back cannot reveal
its range; the ranges above are a choice, and whether values beyond them have an effect was not tested.

## Loudness and balance — investigation (2026-11-15, read-only)

Both store and read back. **Update (2026-11-15):** Loudness was heard working when playing over Wi-Fi, a few seconds after the change, so it is back on the main card; the earlier "no effect" was observed over Bluetooth from the PC (why Bluetooth differs is not verified). Balance is still not heard and stays only in the test lab (the API endpoints are unchanged).

**Verified on this speaker (StreamSDK 1.12.1.1, board `Stream800_demo_client`):**
- The speaker's own menu (`ui:/settings/audio/tone`) lists Postprocessing, Bass, Treble, Loudness and Balance together;
  Balance is declared `slider −10…+10 step 0.5 dB` (same for bass/treble). So both are standard StreamSDK tone settings.
- `settings:/mediaPlayer/alsaMixerElements` maps only `bassElem: Bass`, `trebleElem: Treble`, `muteElem`/`attenuationElem: Master`.
  There is no element for balance or loudness.
- `postprocessing` is already `true`; `volumeOnDsp` is `true`. No other loudness/balance node exists under
  `settings:/mediaPlayer`, `dspControl`, `bw`, `illusonic`, `imx8AudioFramework`, `qcs40xDolby`, `formation`.
- B&W's own app protocol (StateD, `https://<host>:42425`, used by the B&W Music App) answers `get_property` for
  `liberty.property.gain.bass` (100 = 1 dB, mirrors `settings:/mediaPlayer/bass`), `gain.treble` (600) and `gain.offset`
  (-120, meaning unknown). For `gain.balance`, `balance`, `loudness`, `gain.loudness` it answers
  "unsupported property". Nothing was written on either API.
- Public projects (Fosi S3 Home Assistant integration on StreamSDK; space192/zeppelin for this speaker) expose balance only on
  other StreamSDK devices; none expose loudness, and the Zeppelin integration has only bass and treble.

**Hypotheses (not verified):**
- Bass/treble work because they are wired to ALSA mixer controls that B&W's DSP implements; StreamSDK applies balance
  and loudness through its own generic path, which this product's audio pipeline (Illusonic DSP, volume on DSP)
  probably bypasses. That would explain values being stored with no effect.
- No extra activation or alternative path was found. Changing `alsaMixerElements`, `postprocessing` or DSP settings
  might wire them, but those are internal DSP settings and were deliberately not touched.

Test lab (Settings, admin only): tries bass/brightness/colour with saved originals and restore, and records what the user
observed. Kids-mode codes can read the speaker state but cannot change it.

## Bluetooth pairing — investigation (2026-11-15, read-only, nothing written)

**Verified on this speaker:**
- `settings:/bluetooth` holds settings only (e.g. `bluetoothPairingTimeout` 300 s, `disablePairingOncePaired` false,
  `agentCapability` noInputNoOutput, `maxPairedAudioDevices` 8). `bluetooth:` alone is `invalidPath`: the scheme exists only with sub-paths.
- `ui:/bluetooth` lists the speaker's own Bluetooth menu, pointing to nodes under `bluetooth:`:
  - `bluetooth:deviceList/discoverable` — `type: action`, title "Not visible to other devices" (the title reflects the current state).
  - `bluetooth:deviceList/discovery` — `type: action`, "Scan for other Bluetooth devices" (the speaker as a source, for BT speakers).
  - per paired device `bluetooth:devices/<mac_with_underscores>/{play,disconnect,unpair}` — action nodes (`disabled: true` when not applicable).
- `bluetooth:state` (`modifiable: true`, type `bluetoothState`) reports `discoverable`, `pairable`, `discovering`, `connected`,
  `activeDevice`, `connectedDevice` and `pairedDevices`. Now: discoverable=false, pairable=false.

**From public code on the same API (not tried on this speaker):** three independent StreamSDK integrations
(zzznz27/Fosi-S3, herofuve/homeassistant-vssl-mx incl. its APK-derived PROTOCOL.md, sbesh91/aioharmanluxury) invoke action
nodes with `POST /api/setData {"path": <action>, "role": "activate", "value": {}}`. None of them uses the `discoverable` node.

**Observed (2026-11-15, passive watch, read-only):** while the user pressed "Pair new device" in the B&W app, `bluetooth:state`
went `discoverable/pairable: false → true` and the `discoverable` action's title changed to "Visible to other devices"
(at 44 s; again at 132 s after a second press). It returned to false/"Not visible" ~33 s later, when the phone reconnected.
So the app drives exactly this state. Which request the app sends (this node or StateD) was not captured.

**Verified by one test write (2026-11-15, user-approved):** with the speaker not visible, `POST /api/setData
{"path":"bluetooth:deviceList/discoverable","role":"activate","value":{}}` answered `200 null`; within 0.5 s `bluetooth:state`
showed `discoverable/pairable: true` and the title "Visible to other devices". So this action opens pairing mode.

**Hypotheses (not verified):** pairing mode lasts `bluetoothPairingTimeout` (300 s) or until a device connects; activating it again
while visible probably turns it off. The B&W app may instead use its own StateD API (port 42425), which was not examined for pairing.

## Automatic colour cycling (`backend/app/services/colorcycle.py`)

Runs on the server (continues with the browser closed), one task per speaker, started only by an explicit request — never at server start. Each step is an ordinary verified `ambientLightRgb` write, serialised with every other write; brightness is never written. Colours change in steps (the speaker's fade is untested). A manual colour, light off, an address change or server shutdown stops it, keeping the last colour. A disconnected speaker stops it with a message: no retries, no catch-up. Interval 3–3600 s (app limit), palette (2–12 colours) or random; settings are saved in the database.

## Personal profiles (`backend/app/services/profiles.py`)

Stored in SQLite (available from any browser). A profile holds the 5 EQ values, bass, treble, loudness, light colour and brightness, and the colour cycle (running, palette, interval, smooth); volume only when explicitly included. Never stored or changed: mute, balance, source gain, the light on/off switch. Saving reads fresh values (a partial capture is refused). Loading: undo snapshot first, cycle stopped, one verified write per setting, cycle restarted if the profile had it, then read back; every other speaker write is refused meanwhile. Each step reports its result and a partial load is reported as partial (and not marked as loaded). Never loaded automatically.
