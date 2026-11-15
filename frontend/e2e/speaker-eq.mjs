// Zeppelin equalizer card, UI behaviour only. Every /api call is answered here: no backend and no speaker are contacted.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-eq.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 520, height: 2600 } })).newPage()

const NAMES = ['60', '250', '1000', '3500', '12000']
let eq = NAMES.map((band) => ({ min: -6, max: 6, band, step: 0.5, value: 0 }))
const writes = []
let failNext = null
let delayMs = 0
let inFlight = 0, maxInFlight = 0

await page.route('**/api/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/usage') return json({ today_min: 0, days: [{ day: '2026-11-15', total_min: 0, apps: {} }] })
  if (path === '/api/speaker') return json({ host: '192.168.1.52', reachable: true, volume: 23, treble: 5, light: true, bass: 2, brightness: 100, rgb: { red: 24, green: 69, blue: 129 }, errors: {} })
  if (path === '/api/speaker/eq' && req.method() === 'GET') return json({ bands: eq, enabled: true, errors: {} })
  if (path === '/api/speaker/eq' && req.method() === 'POST') {
    const body = JSON.parse(req.postData())
    writes.push(body)
    inFlight++; maxInFlight = Math.max(maxInFlight, inFlight)
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs))
    inFlight--
    if (failNext) { const f = failNext; failNext = null; return json({ detail: { code: f.code, message: f.message } }, f.status) }
    eq = eq.map((x) => ({ ...x, value: body.bands.find((y) => y.band === x.band).value }))
    return json({ bands: eq, enabled: true, errors: {} })
  }
  if (req.method() !== 'GET') writes.push({ unexpected: path })
  return json([])
})

await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true, eqLive: false }, version: 4 })))
await page.goto(base + '/', { waitUntil: 'networkidle' })
const card = page.locator('section', { hasText: 'חמישה תחומים' })
const slider = (name) => card.getByRole('slider', { name })

// 1. Loading reads only; five sliders named after the bands, with the speaker's range and step.
await card.waitFor({ timeout: 10000 }).catch(() => fail('EQ card missing'))
await page.waitForTimeout(1500)
if (writes.length) fail(`writes on load: ${JSON.stringify(writes)}`)
for (const n of ['60Hz', '250Hz', '1kHz', '3.5kHz', '12kHz']) {
  if (!(await slider(n).count())) fail(`slider ${n} missing`)
}
const s60 = slider('60Hz')
if ((await s60.getAttribute('data-step')) !== '0.5' || (await s60.getAttribute('aria-valuemin')) !== '-6' || (await s60.getAttribute('aria-valuemax')) !== '6') fail('range/step not from the speaker')
if (await card.getByText(/לקריאה בלבד|ניסיוני|מתג האקולייזר ברמקול כבוי/).count()) fail('EQ card shows a status line although the switch is on')

// 2. Editing is local: keyboard and dragging on the graph send nothing.
await s60.focus()
await page.keyboard.press('ArrowUp')
await page.keyboard.press('ArrowUp')
await slider('1kHz').focus()
await page.keyboard.press('ArrowUp')
await slider('12kHz').focus()
await page.keyboard.press('ArrowDown')
await page.keyboard.press('ArrowDown')
await slider('3.5kHz').evaluate((el) => el.scrollIntoView({ block: 'center' })) // not under the fixed bottom bar
const h = await slider('3.5kHz').boundingBox() // drag 3.5kHz far up: lands on that band's own max
await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2)
await page.mouse.down()
await page.mouse.move(h.x + h.width / 2, Math.max(2, h.y - 400), { steps: 8 }) // stay inside the window, or the browser drops the events
await page.mouse.up()
if ((await slider('3.5kHz').getAttribute('aria-valuenow')) !== '6') fail('drag did not reach the band max')
await page.waitForTimeout(800)
if (writes.length) fail(`local edits were sent: ${JSON.stringify(writes)}`)
await card.getByText('לא הוחל', { exact: true }).waitFor({ timeout: 2000 }).catch(() => fail('"not applied" chip missing'))

// 3. Apply: exactly one request with all five bands.
await card.getByRole('button', { name: 'החל את האקולייזר על הרמקול' }).click()
await page.getByText(/^האקולייזר הוחל: /).waitFor({ timeout: 5000 }).catch(() => fail('apply success toast missing'))
if (writes.length !== 1) fail(`expected one write, got ${JSON.stringify(writes)}`)
const sent = Object.fromEntries((writes[0]?.bands ?? []).map((x) => [x.band, x.value]))
if (JSON.stringify(sent) !== JSON.stringify({ 60: 1, 250: 0, 1000: 0.5, 3500: 6, 12000: -1 })) fail(`apply body: ${JSON.stringify(writes[0])}`)
if ((await card.getByText('לא הוחל', { exact: true }).count())) fail('still "not applied" after a confirmed apply')
if ((await s60.getAttribute('aria-valuenow')) !== '1') fail('slider does not show the read-back value')

// 4. Reset to 0 is local until applied.
writes.length = 0
await card.getByRole('button', { name: /איפוס כל התחומים/ }).click()
await page.waitForTimeout(500)
if (writes.length) fail('reset sent something before apply')
if ((await s60.getAttribute('aria-valuenow')) !== '0') fail('reset did not move the slider to 0')

// (the success toast from step 3 must be gone first, or it would be mistaken for a new one)
await page.getByText(/^האקולייזר הוחל: /).waitFor({ state: 'detached', timeout: 8000 }).catch(() => fail('old toast never cleared'))
// 5. A speaker error inside HTTP 200 (server: 502 DENIED): error shown, edits kept, no success.
failNext = { status: 502, code: 'DENIED', message: 'הרמקול החזיר שגיאה: Invalid value' }
await card.getByRole('button', { name: 'החל את האקולייזר על הרמקול' }).click()
await page.getByText('הרמקול החזיר שגיאה: Invalid value').waitFor({ timeout: 5000 }).catch(() => fail('speaker error not shown'))
if (await page.getByText(/^האקולייזר הוחל: /).count()) fail('success shown for a failed apply')
if (!(await card.getByText('לא הוחל', { exact: true }).count())) fail('edits lost after a failed apply')

// 6. Undo goes back to the speaker values without sending.
writes.length = 0
await card.getByRole('button', { name: 'בטל את השינויים וחזור לערכי הרמקול' }).click()
if ((await s60.getAttribute('aria-valuenow')) !== '1') fail('undo did not return to the speaker value')
if (writes.length) fail('undo sent something')

// 7. Live mode: dragging sends while it happens, never more than one request at a time, and ends on the dragged value.
await card.getByLabel('שינויים בזמן אמת').check()
if (await card.getByRole('button', { name: 'החל את האקולייזר על הרמקול' }).count()) fail('apply button shown in live mode')
writes.length = 0
delayMs = 250
const h2 = await slider('250Hz').boundingBox()
await page.mouse.move(h2.x + h2.width / 2, h2.y + h2.height / 2)
await page.mouse.down()
for (let i = 1; i <= 12; i++) { await page.mouse.move(h2.x + h2.width / 2, h2.y + h2.height / 2 - i * 6); await page.waitForTimeout(40) }
await page.mouse.up()
const dragged = Number(await slider('250Hz').getAttribute('aria-valuenow'))
await page.waitForTimeout(1500)
if (!writes.length) fail('live drag sent nothing')
if (maxInFlight > 1) fail(`${maxInFlight} EQ requests were in flight at once`)
if (writes.length >= 12) fail(`live drag was not coalesced: ${writes.length} writes for 12 moves`)
if (eq.find((x) => x.band === '250').value !== dragged || dragged <= 0) fail(`speaker ended on ${eq.find((x) => x.band === '250').value}, dragged to ${dragged}`)
if (writes.some((w) => w.bands.length !== 5)) fail('a live write did not carry all five bands')
writes.length = 0
await slider('12kHz').focus()
await page.keyboard.press('ArrowUp')
await page.waitForTimeout(800)
if (writes.length !== 1) fail(`one key press should send once in live mode, sent ${writes.length}`)
delayMs = 0

await card.screenshot({ path: process.env.SHOT ?? 'speaker-eq.png' })
await b.close()
console.log(process.exitCode ? 'speaker eq e2e: FAILED' : 'speaker eq e2e: OK')
