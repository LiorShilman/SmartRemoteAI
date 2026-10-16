# Test plan

Automated: `npm test` (parser), `npm run typecheck`, `npm run build`, `npm run e2e` (demo flow, voice preview, offline honesty).

Manual on real devices (after Steps C–E): pair HOT; D-pad/Home/Back; send 1, 2, 12 with delays 200–800ms, with/without OK; Channel ±; LG pairing prompt on TV; volume/mute/input/power-off; WOL only if MAC known; restart backend and confirm pairing persists; phone over HTTPS for mic + PWA install.
