// B&W Zeppelin card, UI behaviour only. Every /api call is answered by this script: no backend and no speaker are
// contacted, so it is safe to run anywhere.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const ctx = await b.newContext({ viewport: { width: 420, height: 1400 } })
const page = await ctx.newPage()

let speaker = { host: '192.168.1.52', reachable: true, volume: 23, treble: 5, light: true, bass: -1, brightness: 100, rgb: { red: 255, green: 6, blue: 126 }, loudness: false, mute: false, balance: 0, errors: {} }
const writes = []
let failNext = null // { status, code, message } for the next write
let speakerReads = 0
let cycle = { config: { interval_s: 10, mode: 'palette', palette: [{ red: 255, green: 0, blue: 0 }, { red: 0, green: 0, blue: 255 }] },
  status: { running: false, state: 'stopped', message: null, last_colour: null, changed_at: null, steps: 0 } }
const cyclePosts = []
let writeDelayMs = 0 // a slow speaker: the write + read-back takes this long

const STANDBY_OPTS = [[0, 'Off'], [300, '5 minutes'], [600, '10 minutes'], [900, '15 minutes'], [1800, '30 minutes']].map(([seconds, title]) => ({ seconds, title }))
let standby = { seconds: 1200, options: STANDBY_OPTS }
const sources = { sources: [
  { id: 'spdif', title: 'SPDIF', active: false, plugged: false, available: false },
  { id: 'airplay', title: 'AirPlay', active: true, plugged: true, available: true },
  { id: 'bluetooth', title: 'Bluetooth', active: false, plugged: false, available: false }] }
let bt = { name: 'Living Room', discoverable: false, pairable: false, connected_device: 'POCO X7 Pro', paired: ['POCO X7 Pro', 'POCO X7 Pro', 'DESKTOP-TM1E1QQ'], sent: null }
await page.route('**/api/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/usage') return json({ today_min: 0, days: [{ day: '2026-11-15', total_min: 0, apps: {} }] })
  if (path === '/api/speaker' && req.method() === 'GET') { speakerReads++; return json(speaker) }
  if (path === '/api/speaker/cycle' && req.method() === 'GET') return json(cycle)
  if (path.startsWith('/api/speaker/cycle/')) {
    const body = req.postData() ? JSON.parse(req.postData()) : null
    cyclePosts.push({ path, body })
    if (path.endsWith('/config')) { cycle = { ...cycle, config: body }; return json(cycle) }
    if (path.endsWith('/start')) {
      if (!speaker.light) return json({ detail: { code: 'DENIED', message: 'התאורה כבויה. יש להדליק אותה לפני הפעלת החלפת הצבעים.' } }, 409)
      cycle = { ...cycle, status: { ...cycle.status, running: true, state: 'running', message: null, last_colour: { red: 255, green: 0, blue: 0 } } }
      return json(cycle)
    }
    if (path.endsWith('/stop')) { cycle = { ...cycle, status: { ...cycle.status, running: false, state: 'stopped' } }; return json(cycle) }
  }
  if (path === '/api/speaker/sources') return json(sources)
  if (path === '/api/speaker/standby' && req.method() === 'GET') return json(standby)
  if (path === '/api/speaker/standby') {
    const body = JSON.parse(req.postData() || '{}')
    writes.push({ path, body })
    standby = { ...standby, seconds: body.seconds }
    return json(standby)
  }
  if (path === '/api/speaker/bluetooth') return json(bt)
  if (path === '/api/speaker/bluetooth/pairing') {
    writes.push({ path, body: null })
    if (bt.discoverable) return json({ ...bt, sent: false })
    bt = { ...bt, discoverable: true, pairable: true }
    return json({ ...bt, sent: true })
  }
  if (path === '/api/speaker/eq' && req.method() === 'GET') return json({ bands: ['60', '250', '1000', '3500', '12000'].map((band) => ({ min: -6, max: 6, band, step: 0.5, value: 0 })), enabled: true, errors: {} })
  if (path === '/api/speaker/lab' && req.method() === 'GET') return json({ host: speaker.host, snapshot: null, current: { bass: 0, brightness: 40, rgb: { red: 255, green: 6, blue: 126 } }, errors: {}, last: {}, observations: [] })
  if (path.startsWith('/api/speaker/') && req.method() !== 'GET') {
    const body = JSON.parse(req.postData() || '{}')
    writes.push({ path, body })
    if (writeDelayMs) await new Promise((r) => setTimeout(r, writeDelayMs))
    if (failNext) { const f = failNext; failNext = null; return json({ detail: { code: f.code, message: f.message } }, f.status) }
    if (path.endsWith('/volume')) speaker = { ...speaker, volume: body.value }
    if (path.endsWith('/treble')) speaker = { ...speaker, treble: body.value }
    if (path.endsWith('/light')) speaker = { ...speaker, light: body.enabled }
    if (path.endsWith('/bass')) speaker = { ...speaker, bass: body.value }
    if (path.endsWith('/brightness')) speaker = { ...speaker, brightness: body.value }
    if (path.endsWith('/rgb')) { speaker = { ...speaker, rgb: body }; if (cycle.status.running) cycle = { ...cycle, status: { ...cycle.status, running: false, state: 'stopped', message: 'נבחר צבע ידני' } } }
    if (path.endsWith('/loudness')) speaker = { ...speaker, loudness: body.enabled }
    if (path.endsWith('/mute')) speaker = { ...speaker, mute: body.enabled }
    if (path.endsWith('/balance')) speaker = { ...speaker, balance: body.value }
    if (path.endsWith('/config')) speaker = { ...speaker, host: body.host }
    return json(speaker)
  }
  return json([])
})

await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true }, version: 4 })))
await page.goto(base + '/', { waitUntil: 'networkidle' })

// 1. Loading the screen reads the speaker and writes nothing.
await page.getByText('Bowers & Wilkins Zeppelin').waitFor({ timeout: 10000 }).catch(() => fail('speaker card missing'))
await page.locator('section', { hasText: 'Bowers & Wilkins Zeppelin' }).getByText('מחובר', { exact: true }).waitFor({ timeout: 8000 }).catch(() => fail('connected chip missing'))
await page.waitForTimeout(2500)
if (writes.length) fail(`writes on load: ${JSON.stringify(writes)}`)
if ((await page.getByRole('slider', { name: 'עוצמה' }).inputValue()) !== '23') fail('volume not shown from the speaker state')
// shown in the speaker's own 0..50 (no conversion)
if (!(await page.getByText('23', { exact: true }).count())) fail('volume not shown as the speaker number 23')
if ((await page.getByRole('slider', { name: 'עוצמה' }).getAttribute('max')) !== '50') fail('volume slider max is not the speaker max 50')
// bass and treble: the declared -10..+10 in half steps
for (const n of ['באס', 'גבוהים']) {
  const sl = page.getByRole('slider', { name: n })
  const got = [await sl.getAttribute('min'), await sl.getAttribute('max'), await sl.getAttribute('step')].join(' ')
  if (got !== '-10 10 0.5') fail(`slider ${n}: min/max/step ${got}, expected -10 10 0.5`)
}

// dial: - on the left (minimum end of the clockwise arc), + on the right
const minus = await page.getByRole('button', { name: 'הנמך עוצמה' }).boundingBox(), plus0 = await page.getByRole('button', { name: 'הגבר עוצמה' }).boundingBox()
if (!(minus.x < plus0.x)) fail('dial: - should be left of +')
// every slider: Hebrew order (+ left, - right) and the track itself runs right-to-left, so + sits at its maximum end
for (const n of ['באס', 'גבוהים', 'בהירות']) {
  const bm = await page.getByRole('button', { name: 'הנמך ' + n }).boundingBox(), bp = await page.getByRole('button', { name: 'הגבר ' + n }).boundingBox()
  if (!(bp.x < bm.x)) fail(`slider ${n}: + should be left of -`)
  const dir = await page.getByRole('slider', { name: n }).evaluate((el) => getComputedStyle(el).direction)
  if (dir !== 'rtl') fail(`slider ${n}: runs ${dir}, expected rtl`)
}

// 2. Refresh is read-only too.
await page.getByRole('button', { name: 'רענן את מצב הרמקול' }).click()
await page.waitForTimeout(800)
if (writes.length) fail('refresh wrote to the speaker')

// 3. Light toggle sends exactly one write, success only after the server confirmed.
await page.getByRole('switch', { name: 'כבה את תאורת הרמקול' }).click()
await page.getByText('התאורה כובתה').waitFor({ timeout: 5000 }).catch(() => fail('no success toast for light'))
if (writes.length !== 1 || writes[0].path !== '/api/speaker/light' || writes[0].body.enabled !== false) fail(`light write: ${JSON.stringify(writes)}`)
await page.getByRole('switch', { name: 'הדלק את תאורת הרמקול' }).waitFor({ timeout: 3000 }).catch(() => fail('light state not updated'))

// 4. Keyboard on the volume slider: one arrow press -> one write of that value.
writes.length = 0
await page.getByRole('slider', { name: 'עוצמה' }).focus()
await page.keyboard.press('ArrowUp')
await page.waitForTimeout(1200)
if (writes.length !== 1 || writes[0].path !== '/api/speaker/volume' || writes[0].body.value !== 24) fail(`slider write: ${JSON.stringify(writes)}`)
await page.getByRole('slider', { name: 'עוצמה' }).blur() // blur with no new value must not resend
await page.waitForTimeout(500)
if (writes.length !== 1) fail('blur re-sent the same value')

// 4b. Slow speaker + quick presses: the buttons are never disabled (no "not allowed" cursor flash) and no press is
// lost: three presses on + move three steps, sent one after another as each is confirmed.
writes.length = 0
writeDelayMs = 500
const plus = page.getByRole('button', { name: 'הגבר עוצמה' })
const startVol = speaker.volume
for (let i = 0; i < 3; i++) {
  await plus.click({ timeout: 1000 }).catch(() => fail('+ button not clickable while a change is on its way'))
  if (await plus.isDisabled()) fail('+ button disabled while a change is on its way')
  await page.waitForTimeout(120)
}
await page.waitForTimeout(2500)
writeDelayMs = 0
if (speaker.volume !== startVol + 3) fail(`quick presses lost: volume ${speaker.volume}, expected ${startVol + 3} (writes: ${JSON.stringify(writes)})`)
if (writes.length > 3) fail(`too many writes for 3 presses: ${writes.length}`)
if ((await page.getByRole('slider', { name: 'עוצמה' }).inputValue()) !== String(startVol + 3)) fail('slider does not show the confirmed value')

// 4c. Bass, brightness and colour: each sends its own control, once.
writes.length = 0
await page.getByRole('button', { name: 'הגבר באס' }).click()
await page.getByText('באס: -0.5').waitFor({ timeout: 5000 }).catch(() => fail('bass success toast missing (half step from -1)'))
if (writes.length !== 1 || writes[0].path !== '/api/speaker/bass' || writes[0].body.value !== -0.5) fail(`bass write: ${JSON.stringify(writes)}`)
writes.length = 0
await page.getByRole('button', { name: 'הנמך בהירות' }).click()
await page.waitForTimeout(800)
if (writes.length !== 1 || writes[0].path !== '/api/speaker/brightness' || writes[0].body.value !== 90) fail(`brightness write: ${JSON.stringify(writes)}`)
writes.length = 0
await page.getByLabel('צבע התאורה').fill('#184581')
await page.getByText('צבע התאורה עודכן').waitFor({ timeout: 5000 }).catch(() => fail('colour success toast missing'))
if (writes.length !== 1 || writes[0].path !== '/api/speaker/rgb' || JSON.stringify(writes[0].body) !== JSON.stringify({ red: 24, green: 69, blue: 129 })) fail(`rgb write: ${JSON.stringify(writes)}`)

// 4e. Mute: one write, disabled while on its way.
writes.length = 0
const mute = page.getByRole('switch', { name: /השתק/ })
if ((await mute.getAttribute('aria-checked')) !== 'false') fail('mute state not read on load')
writeDelayMs = 500
await mute.click()
await page.waitForTimeout(120)
if (!(await page.getByRole('switch', { name: /השתק/ }).isDisabled())) fail('mute switch not disabled during the request')
await page.waitForTimeout(900)
writeDelayMs = 0
if (writes.length !== 1 || writes[0].path !== '/api/speaker/mute' || writes[0].body.enabled !== true) fail(`mute write: ${JSON.stringify(writes)}`)
if ((await page.getByRole('switch', { name: /השתק/ }).getAttribute('aria-checked')) !== 'true') fail('mute not shown on after confirm')
// Loudness is back on the main card (effect heard over Wi-Fi, after a few seconds); balance stays only in the lab.
for (const x of [page.getByRole('slider', { name: 'איזון' }), page.getByText('ניסיוני')])
  if (await x.count()) fail('balance/"experimental" shown on the main card')
writes.length = 0
await page.getByRole('switch', { name: 'הפעל Loudness' }).click({ timeout: 3000 }).catch(() => fail('Loudness switch missing'))
await page.getByRole('switch', { name: 'כבה Loudness' }).waitFor({ timeout: 3000 }).catch(() => fail('Loudness not shown as on after the speaker confirmed'))
if (writes.length !== 1 || !writes[0].path.endsWith('/loudness') || writes[0].body.enabled !== true) fail(`loudness write: ${JSON.stringify(writes)}`)
await page.getByRole('switch', { name: 'כבה Loudness' }).click()
await page.getByRole('switch', { name: 'הפעל Loudness' }).waitFor({ timeout: 3000 }).catch(() => fail('Loudness not turned off'))
writes.length = 0

// Audio source: read only, from the speaker's own list; no switching offered.
await page.getByText('מנגן עכשיו מ-AirPlay').waitFor({ timeout: 3000 }).catch(() => fail('active source not shown'))
// Standby: the unlisted current value (20 min) is shown, nothing written on load; one write on a choice.
const sb = page.getByRole('combobox', { name: 'כיבוי אוטומטי אחרי זמן ללא השמעה' })
if ((await sb.inputValue().catch(() => '')) !== '1200') fail('standby: current 1200 not selected')
if (writes.length) fail(`writes before choosing standby: ${JSON.stringify(writes)}`)
// readable: the options list uses the dark drop-down style (not white with light text)
const optBg = await sb.locator('option').nth(1).evaluate((o) => getComputedStyle(o).backgroundColor)
if (optBg !== 'rgb(17, 24, 43)') fail(`standby options background is ${optBg}, expected the dark #11182b`)
await sb.selectOption('1800')
await page.getByText('כיבוי אוטומטי: 30 דקות').waitFor({ timeout: 3000 }).catch(() => fail('standby toast missing'))
if (writes.length !== 1 || writes[0].path !== '/api/speaker/standby' || writes[0].body.seconds !== 1800) fail(`standby writes: ${JSON.stringify(writes)}`)
writes.length = 0

// Bluetooth pairing: shown from what the speaker reports, sent only on a press, then no button while visible.
await page.getByText('מחובר עכשיו: POCO X7 Pro').waitFor({ timeout: 3000 }).catch(() => fail('bluetooth state not shown'))
await page.getByRole('button', { name: 'פתח מצב צימוד Bluetooth' }).click({ timeout: 3000 }).catch(() => fail('pairing button missing'))
await page.getByText('גלוי לצימוד בשם').waitFor({ timeout: 3000 }).catch(() => fail('visible state not shown after the speaker confirmed'))
if (writes.length !== 1 || writes[0].path !== '/api/speaker/bluetooth/pairing') fail(`pairing writes: ${JSON.stringify(writes)}`)
if (await page.getByRole('button', { name: 'פתח מצב צימוד Bluetooth' }).count()) fail('pairing button still offered while visible')
bt = { ...bt, discoverable: false, pairable: false }
writes.length = 0

// 4f. Automatic colour cycling: settings saved on the server, explicit start/stop, refused with the light off,
// and a manual colour stops it. Brightness is never written by any of this.
if (await page.getByRole('switch', { name: 'הדלק את תאורת הרמקול' }).count()) { await page.getByRole('switch', { name: 'הדלק את תאורת הרמקול' }).click(); await page.waitForTimeout(700) }
writes.length = 0
cyclePosts.length = 0
await page.getByLabel('מרווח בין צבעים').fill('5')
await page.getByLabel('מרווח בין צבעים').press('Enter')
await page.waitForTimeout(400)
if (cyclePosts.at(-1)?.body?.interval_s !== 5) fail(`interval not saved: ${JSON.stringify(cyclePosts)}`)
await page.getByLabel('מרווח בין צבעים').fill('2')
if (!(await page.getByText('בין 3 ל־3600 שניות.').count())) fail('too-short interval not flagged')
await page.getByLabel('מרווח בין צבעים').fill('5')
await page.getByRole('radio', { name: 'צבעים: אקראי' }).click()
await page.waitForTimeout(400)
if (cyclePosts.at(-1)?.body?.mode !== 'random') fail('mode not saved')
await page.getByRole('radio', { name: 'צבעים: הפלטה שלי' }).click()
await page.waitForTimeout(400)
await page.getByLabel('מעבר הדרגתי').check()
await page.waitForTimeout(400)
if (cyclePosts.at(-1)?.body?.smooth !== true) fail('smooth not saved')
const cyc = page.getByRole('switch', { name: /החלפת צבעים אוטומטית/ })
await cyc.click()
await page.getByRole('switch', { name: 'עצור החלפת צבעים אוטומטית' }).waitFor({ timeout: 4000 }).catch(() => fail('running state not shown'))
if (!cyclePosts.some((x) => x.path.endsWith('/start'))) fail('start not sent')
await page.getByLabel('צבע התאורה').fill('#112233') // manual colour -> the server stops the cycle
await page.waitForTimeout(900)
if ((await page.getByRole('switch', { name: /החלפת צבעים אוטומטית/ }).getAttribute('aria-checked')) !== 'false') fail('manual colour did not stop the cycle in the UI')
await page.getByText('נבחר צבע ידני').waitFor({ timeout: 3000 }).catch(() => fail('stop reason not shown'))
if (writes.some((w) => w.path.endsWith('/brightness'))) fail('cycling touched the brightness')
// light off: cannot start, with the message
await page.getByRole('switch', { name: 'כבה את תאורת הרמקול' }).click()
await page.waitForTimeout(700)
await page.getByText('יש להדליק את התאורה לפני הפעלת החלפת הצבעים.').waitFor({ timeout: 3000 }).catch(() => fail('light-off message missing'))
if (!(await page.getByRole('switch', { name: /החלפת צבעים אוטומטית/ }).isDisabled())) fail('cycle can be started with the light off')
await page.getByRole('switch', { name: 'הדלק את תאורת הרמקול' }).click()
await page.waitForTimeout(700)

// 5. Speaker error inside HTTP 200 (server maps it to 502 DENIED): error shown, no success.
writes.length = 0
failNext = { status: 502, code: 'DENIED', message: 'הרמקול החזיר שגיאה: Invalid value' }
await page.getByRole('button', { name: 'הגבר גבוהים' }).click()
await page.getByText('הרמקול החזיר שגיאה: Invalid value').waitFor({ timeout: 5000 }).catch(() => fail('speaker error not shown'))
if (await page.getByText(/^גבוהים: /).count()) fail('success shown for a failed write')
if (writes.length !== 1 || writes[0].body.value !== 5.5) fail(`treble write: ${JSON.stringify(writes)}`)

// 6. Speaker unreachable: clear message, controls hidden, nothing written.
writes.length = 0
speaker = { ...speaker, reachable: false, volume: null, treble: null, light: null, bass: null, brightness: null, rgb: null, errors: { volume: 'אין חיבור' } }
await page.getByRole('button', { name: 'רענן את מצב הרמקול' }).click()
await page.getByText('הרמקול לא עונה בכתובת').waitFor({ timeout: 5000 }).catch(() => fail('unreachable message missing'))
if (await page.getByRole('slider', { name: 'עוצמה' }).count()) fail('controls shown while the speaker is unreachable')
if (writes.length) fail('wrote while unreachable')

// 7. Admin changes the address in Settings.
speaker = { host: '192.168.1.52', reachable: true, volume: 23, treble: 5, light: true, bass: -1, brightness: 100, rgb: { red: 255, green: 6, blue: 126 }, loudness: false, mute: false, balance: 0, errors: {} }
await page.goto(base + '/settings', { waitUntil: 'networkidle' })
await page.getByLabel('כתובת הרמקול').fill('192.168.1.60')
await page.getByRole('button', { name: 'שמור כתובת רמקול' }).click()
await page.getByText('הכתובת נשמרה והרמקול עונה').waitFor({ timeout: 5000 }).catch(() => fail('address save not confirmed'))
const cfg = writes.filter((w) => w.path === '/api/speaker/config')
if (cfg.length !== 1 || cfg[0].body.host !== '192.168.1.60') fail(`config write: ${JSON.stringify(cfg)}`)
if (writes.some((w) => w.path !== '/api/speaker/config')) fail('opening settings wrote to the speaker')

// 8. Success toasts off (the default): a confirmed change shows no toast, an error still does.
await page.getByLabel('הצג הודעת אישור אחרי פעולה מוצלחת').uncheck()
await page.goto(base + '/', { waitUntil: 'networkidle' })
writes.length = 0
await page.getByRole('switch', { name: /תאורת הרמקול/ }).click()
await page.waitForTimeout(1200)
if (writes.length !== 1) fail('light change not sent with toasts off')
if (await page.getByText(/^התאורה (הודלקה|כובתה)$/).count()) fail('success toast shown although turned off')
failNext = { status: 502, code: 'DENIED', message: 'הרמקול החזיר שגיאה: Invalid value' }
await page.getByRole('button', { name: 'הגבר עוצמה' }).click()
await page.getByText('הרמקול החזיר שגיאה: Invalid value').waitFor({ timeout: 5000 }).catch(() => fail('error toast hidden with success toasts off'))

await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.locator('section', { hasText: 'Bowers & Wilkins Zeppelin' }).first().screenshot({ path: process.env.SHOT ?? 'speaker-card.png' })
await b.close()
console.log(process.exitCode ? 'speaker e2e: FAILED' : 'speaker e2e: OK')
