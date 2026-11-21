// TV page: sound status and the speaker link. All /api calls mocked: no backend, no TV, no speaker.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/tv-audio.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 1280, height: 1600 } })).newPage()

const writes = []
let audio = { state: 'ready', output: 'bt_soundbar', output_kind: 'bluetooth', output_label: "סאונדבר בבלוטות'", tv_volume: 70, tv_muted: false }
let connected = 'LG TV[TV]'
let active = 'bluetooth'
const caps = { nav: 'supported', volume: 'supported', mute: 'supported', power_off: 'supported', inputs: 'supported', apps: 'supported', wol: 'unsupported' }
await page.route('**/api/**', async (route) => {
  const req = route.request(), path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  if (req.method() !== 'GET') writes.push(path)
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([{ id: 'tv1', kind: 'lg', role: 'tv', name: 'טלוויזיה', host: '192.168.1.65', connection: 'connected', capabilities: caps, last_error: null, audio }])
  if (path.endsWith('/commands')) { audio = { ...audio, tv_volume: audio.tv_volume + 3 }; return json({ status: 'sent', request_id: 'x' }) }
  if (path === '/api/speaker/bluetooth') return json({ name: 'Living Room', discoverable: false, pairable: false, connected_device: connected, paired: [], devices: [], pairing_seconds: 300 })
  if (path === '/api/speaker/sources') return json({ sources: ['spdif', 'airplay', 'bluetooth'].map((id) => ({ id, title: id, active: id === active, plugged: true, available: true })) })
  if (path === '/api/speaker') return json({ host: '192.168.1.52', reachable: true, volume: 35, treble: 0, light: true, bass: 0, brightness: 50, rgb: null, mute: false, loudness: false, balance: 0, power: 'online', power_reason: null, errors: {} })
  return json([])
})
await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: false }, version: 4 })))
await page.goto(base + '/tv', { waitUntil: 'networkidle' })
const status = page.getByRole('status', { name: 'מצב הקול של הטלוויזיה' })

// 1. Bluetooth to the verified speaker: both volumes, each labelled, and the link to the speaker page. Nothing sent.
await status.waitFor({ timeout: 6000 }).catch(() => fail('sound status missing'))
if (!(await status.textContent()).includes("סאונדבר בבלוטות'")) fail('output label missing')
await page.getByText('עוצמת טלוויזיה').waitFor({ timeout: 3000 }).catch(() => fail('TV volume missing'))
await page.getByText('הרמקול Zeppelin מנגן את הטלוויזיה').waitFor({ timeout: 6000 }).catch(() => fail('verified speaker not shown'))
await page.getByText('עוצמת רמקול').waitFor({ timeout: 6000 }).catch(() => fail('speaker volume missing'))
if (writes.length) fail(`sent on load: ${writes}`)
await page.screenshot({ path: 'tv-audio-verified.png', fullPage: true })

// 2. The TV volume button still sends the same TV command, and the shown TV volume follows.
await page.getByRole('button', { name: 'הגבר עוצמה' }).click()
await page.getByText('73', { exact: true }).waitFor({ timeout: 4000 }).catch(() => fail('TV volume not refreshed after the press'))
if (JSON.stringify(writes) !== '["/api/devices/tv1/commands"]') fail(`volume press: ${writes}`)
writes.length = 0

// 3. The link opens the speaker page (no command).
await page.getByRole('link', { name: /עוצמה, EQ ופרופילים ברמקול/ }).click()
await page.waitForURL('**/speaker', { timeout: 4000 }).catch(() => fail('link did not open the speaker page'))
if (writes.length) fail(`link sent something: ${writes}`)

// 4. Bluetooth but the speaker plays a phone: not verified, no speaker controls.
connected = 'POCO X7 Pro'
await page.goto(base + '/tv', { waitUntil: 'networkidle' })
await page.getByText('שלא זוהה כרמקול שלנו').waitFor({ timeout: 6000 }).catch(() => fail('unverified Bluetooth not explained'))
if (await page.getByText('הרמקול Zeppelin מנגן את הטלוויזיה').count()) fail('speaker shown for a different Bluetooth device')

// 5. TV speakers: no speaker box, speaker not even asked.
audio = { ...audio, output: 'tv_speaker', output_kind: 'tv_speaker', output_label: 'רמקולי הטלוויזיה', tv_muted: true }
connected = 'LG TV[TV]'
const asked = []
page.on('request', (r) => { if (r.url().includes('/api/speaker')) asked.push(r.url()) })
await page.goto(base + '/tv', { waitUntil: 'networkidle' })
await page.getByText('רמקולי הטלוויזיה').waitFor({ timeout: 6000 }).catch(() => fail('TV speakers label missing'))
await page.getByText('מושתקת').waitFor({ timeout: 3000 }).catch(() => fail('muted not shown'))
if (await page.getByText('הרמקול Zeppelin').count()) fail('speaker shown while TV speakers play')
if (asked.length) fail(`speaker queried while TV speakers play: ${asked.length}`)

// 6. Disconnected / waiting: no stale numbers.
audio = { state: 'offline', output: null, output_kind: null, output_label: null, tv_volume: null, tv_muted: null }
await page.goto(base + '/tv', { waitUntil: 'networkidle' })
await page.getByText('מצב הקול לא זמין').waitFor({ timeout: 6000 }).catch(() => fail('offline not shown'))
if (await page.getByText('עוצמת טלוויזיה').count()) fail('stale TV volume shown while offline')
audio = { ...audio, state: 'pending' }
await page.goto(base + '/tv', { waitUntil: 'networkidle' })
await page.getByText('ממתין לנתוני קול').waitFor({ timeout: 6000 }).catch(() => fail('pending not shown'))
if (writes.length) fail(`sent: ${writes}`)
await b.close()
if (!process.exitCode) console.log('tv-audio e2e: ok')
