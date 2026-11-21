// Speaker restart, UI behaviour only. Every /api call is answered here: no backend, no speaker.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-reboot.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 800, height: 2200 } })).newPage()

const writes = []
let reboot = { phase: 'idle', seconds: null }
let reachable = true
await page.route('**/api/**', async (route) => {
  const req = route.request(), path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (req.method() !== 'GET') writes.push(path)
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/speaker') return json(reachable
    ? { host: '192.168.1.52', reachable: true, volume: 20, treble: 0, light: true, bass: 0, brightness: 50, rgb: { red: 0, green: 0, blue: 255 }, mute: false, loudness: false, balance: 0, power: 'online', power_reason: 'userActivity', errors: {} }
    : { host: '192.168.1.52', reachable: false, volume: null, treble: null, light: null, bass: null, brightness: null, rgb: null, mute: null, loudness: null, balance: null, power: null, power_reason: null, errors: { volume: 'אין חיבור' } })
  if (path === '/api/speaker/reboot' && req.method() === 'POST') {
    reboot = { phase: 'restarting', seconds: 0 }; reachable = false
    return json(reboot)
  }
  if (path === '/api/speaker/reboot') return json(reboot)
  if (path === '/api/speaker/standby') return json({ seconds: 1200, options: [{ seconds: 0, title: 'Off' }, { seconds: 1200, title: '20' }] })
  if (path === '/api/speaker/bluetooth') return json({ name: 'Living Room', discoverable: false, pairable: false, connected_device: null, paired: [], devices: [], pairing_seconds: 300 })
  if (path === '/api/speaker/sources') return json({ sources: [] })
  if (path === '/api/speaker/cycle') return json({ config: { interval_s: 10, mode: 'random', smooth: false, palette: [] }, status: { running: false, state: 'stopped', message: null, last_colour: null, changed_at: null, steps: 0 } })
  if (path === '/api/speaker/profiles') return json({ profiles: [], loaded_id: null, undo: null, loading: false })
  if (path === '/api/speaker/eq') return json({ bands: [], enabled: true, errors: {} })
  return json([])
})
await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true }, version: 4 })))
await page.goto(base + '/speaker', { waitUntil: 'networkidle' })

// 1. The first press only asks; nothing is sent.
const btn = page.getByRole('button', { name: 'הפעל מחדש את הרמקול' })
await btn.waitFor({ timeout: 6000 }).catch(() => fail('restart button missing'))
await btn.click()
await page.getByText(/מכשירי Bluetooth יצטרכו להתחבר שוב/).waitFor({ timeout: 3000 }).catch(() => fail('no confirmation step'))
await page.waitForTimeout(400)
if (writes.length) fail(`sent before confirming: ${writes}`)
// cancel keeps everything as it was
await page.getByRole('button', { name: 'בטל הפעלה מחדש' }).click()
if (writes.length) fail('cancel sent something')

// 2. Confirm: one POST; the card shows "restarting", not the "speaker does not answer" alarm.
await btn.click()
await page.getByRole('button', { name: 'אשר הפעלה מחדש של הרמקול' }).click()
await page.getByText('הרמקול מופעל מחדש…').waitFor({ timeout: 4000 }).catch(() => fail('restarting status missing'))
if (JSON.stringify(writes) !== JSON.stringify(['/api/speaker/reboot'])) fail(`writes: ${writes}`)
await page.waitForTimeout(5500) // a few polls while it is down
if (await page.getByText(/הרמקול לא עונה בכתובת/).count()) fail('unreachable alarm shown during a restart')
if (await page.getByText(/חזר לפעול/).count()) fail('"back" announced before the server saw it')

// 3. The server reports it back: announced once, the card returns.
reboot = { phase: 'back', seconds: 34 }; reachable = true
await page.getByText('הרמקול חזר לפעול (אחרי 34 שניות)').waitFor({ timeout: 6000 }).catch(() => fail('"back" not announced'))
await page.getByRole('slider', { name: 'עוצמה' }).waitFor({ timeout: 8000 }).catch(() => fail('controls did not return'))
if (writes.length !== 1) fail(`extra writes: ${writes}`)

// 4. Opening the page after a finished restart announces nothing.
await page.reload({ waitUntil: 'networkidle' })
await page.waitForTimeout(800)
if (await page.getByText(/חזר לפעול/).count()) fail('old restart announced again on load')
await page.screenshot({ path: 'speaker-reboot.png', fullPage: true })
await b.close()
if (!process.exitCode) console.log('speaker-reboot e2e: ok')
