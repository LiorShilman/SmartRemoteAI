// Speaker page on a phone: tabs, a volume bar that stays on top, and nothing sent by scrolling. All /api calls mocked.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-phone.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const ctx = await b.newContext({ viewport: { width: 390, height: 780 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const cdp = await ctx.newCDPSession(page)

const writes = []
let sp = { host: '192.168.1.52', reachable: true, volume: 20, treble: 0, light: true, bass: 0, brightness: 50, rgb: { red: 0, green: 0, blue: 255 }, mute: false, loudness: false, balance: 0, power: 'online', power_reason: 'userActivity', errors: {} }
let eq = ['60', '250', '1000', '3500', '12000'].map((band) => ({ band, min: -6, max: 6, step: 0.5, value: 0 }))
await page.route('**/api/**', async (route) => {
  const req = route.request(), path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  const body = req.postData() ? JSON.parse(req.postData()) : null
  if (req.method() !== 'GET') writes.push({ path, body })
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/speaker') return json(sp)
  if (path === '/api/speaker/volume') { sp = { ...sp, volume: body.value }; return json(sp) }
  if (path === '/api/speaker/mute') { sp = { ...sp, mute: body.enabled }; return json(sp) }
  if (path === '/api/speaker/eq' && req.method() === 'POST') { eq = eq.map((x) => ({ ...x, value: body.bands.find((y) => y.band === x.band).value })); return json({ bands: eq, enabled: true, errors: {} }) }
  if (path === '/api/speaker/eq') return json({ bands: eq, enabled: true, errors: {} })
  if (path === '/api/speaker/reboot') return json({ phase: 'idle', seconds: null })
  if (path === '/api/speaker/standby') return json({ seconds: 1200, options: [{ seconds: 0, title: 'Off' }, { seconds: 1200, title: '20' }] })
  if (path === '/api/speaker/bluetooth') return json({ name: 'Living Room', discoverable: false, pairable: false, connected_device: 'POCO X7 Pro', paired: [], devices: [], pairing_seconds: 300 })
  if (path === '/api/speaker/sources') return json({ sources: [{ id: 'bluetooth', title: 'Bluetooth', active: true, plugged: true, available: true }] })
  if (path === '/api/speaker/cycle') return json({ config: { interval_s: 10, mode: 'random', smooth: false, palette: [] }, status: { running: false, state: 'stopped', message: null, last_colour: null, changed_at: null, steps: 0 } })
  if (path === '/api/speaker/profiles') return json({ profiles: [], loaded_id: null, undo: null, loading: false })
  return json([])
})
await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => { localStorage.removeItem('speaker-tab'); localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true, eqLive: true }, version: 4 })) })
await page.goto(base + '/speaker', { waitUntil: 'networkidle' })

const tab = (name) => page.getByRole('tab', { name })
const center = async (loc) => { const r = await loc.boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, r } }
/** A real touch scroll (the browser's own gesture) that starts on the given element. */
const touchScroll = async (loc, dy) => {
  await loc.scrollIntoViewIfNeeded()
  const { x, y } = await center(loc)
  await cdp.send('Input.synthesizeScrollGesture', { x: Math.round(x), y: Math.round(y), yDistance: -dy, gestureSourceType: 'touch', speed: 1200 })
  await page.waitForTimeout(500)
}

// 1. Layout: one card with tabs, "צליל" first, EQ as rows (no graph), no separate EQ card, nothing sent on load.
await tab('צליל').waitFor({ timeout: 6000 }).catch(() => fail('tabs missing'))
if ((await tab('צליל').getAttribute('aria-selected')) !== 'true') fail('sound tab not selected by default')
await page.getByRole('button', { name: 'הגבר 60Hz' }).waitFor({ timeout: 4000 }).catch(() => fail('EQ rows missing'))
if (await page.locator('svg[role="group"]').count()) fail('EQ graph shown on a phone')
if (await page.getByRole('heading', { name: 'אקולייזר' }).count() !== 1) fail('EQ shown twice')
if (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) > 0) fail('sideways scroll')
await page.screenshot({ path: 'speaker-phone-sound.png', fullPage: true })
if (writes.length) fail(`sent on load: ${JSON.stringify(writes)}`)

// 2. Scrolling with a finger that lands on the volume bar, the bass slider or the EQ rows sends nothing.
const volBar = page.locator('[role="tablist"]').locator('xpath=..').locator('.h-11').first()
await touchScroll(volBar, 300)
await touchScroll(page.locator('#speaker-tab-sound .h-11').first(), 300)
await touchScroll(page.getByRole('list', { name: 'תחומי האקולייזר' }), 250)
await touchScroll(page.getByRole('list', { name: 'תחומי האקולייזר' }), -600)
if (writes.length) fail(`scrolling changed something: ${JSON.stringify(writes)}`)
if ((await page.evaluate(() => window.scrollY)) === 0 && (await page.evaluate(() => document.documentElement.scrollHeight)) > 900) fail('touch scroll over the controls did not scroll the page')

// 3. The volume bar stays visible after scrolling down.
await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
await page.waitForTimeout(300)
const vb = await page.getByRole('tablist').boundingBox()
if (!vb || vb.y < 0 || vb.y > 780) fail(`tabs/volume not kept on screen: ${JSON.stringify(vb)}`)

// 4. A tap on the volume track does not jump; a sideways drag changes it once, on release.
await page.evaluate(() => window.scrollTo(0, 0))
await page.waitForTimeout(200)
const track = await center(volBar)
await page.mouse.click(track.x + 60, track.y)
await page.waitForTimeout(400)
if (writes.length) fail(`a tap changed the volume: ${JSON.stringify(writes)}`)
await page.mouse.move(track.x, track.y); await page.mouse.down()
for (let i = 1; i <= 8; i++) await page.mouse.move(track.x - i * 10, track.y + 1)
await page.mouse.up()
await page.waitForTimeout(600)
const vol = writes.filter((w) => w.path === '/api/speaker/volume')
if (vol.length !== 1 || !(vol[0].body.value > 20)) fail(`sideways drag: ${JSON.stringify(writes)}`)
writes.length = 0

// 5. EQ +: one press = +1 dB for that band only, sent once.
await page.getByRole('button', { name: 'הגבר 60Hz' }).click()
await page.waitForTimeout(600)
const eqw = writes.filter((w) => w.path === '/api/speaker/eq')
if (eqw.length !== 1 || eqw[0].body.bands.find((x) => x.band === '60').value !== 1 || eqw[0].body.bands.some((x) => x.band !== '60' && x.value !== 0)) fail(`EQ +: ${JSON.stringify(writes)}`)
writes.length = 0

// 6. Mute from the bar.
await page.getByRole('button', { name: 'השתק את הרמקול' }).click()
await page.waitForTimeout(500)
if (JSON.stringify(writes.map((w) => w.path)) !== '["/api/speaker/mute"]') fail(`mute: ${JSON.stringify(writes)}`)
writes.length = 0

// 7. Tabs: only show, never send; the choice is kept.
for (const [name, text] of [['תאורה', 'החלפת צבעים'], ['פרופילים', 'שם לפרופיל חדש'], ['עוד', 'הפעלה מחדש']]) {
  await tab(name).click()
  const found = name === 'פרופילים' ? page.getByLabel(text) : page.getByText(text).first()
  await found.waitFor({ timeout: 4000 }).catch(() => fail(`tab ${name} content missing`))
  await page.screenshot({ path: `speaker-phone-${name === 'תאורה' ? 'light' : name === 'עוד' ? 'more' : 'profiles'}.png`, fullPage: true })
}
if (await page.getByRole('button', { name: 'הגבר 60Hz' }).count()) fail('EQ still shown outside its tab')
await page.reload({ waitUntil: 'networkidle' })
await tab('עוד').waitFor({ timeout: 6000 })
if ((await tab('עוד').getAttribute('aria-selected')) !== 'true') fail('tab choice not kept')
if (writes.length) fail(`tabs sent something: ${JSON.stringify(writes)}`)

// 8. Desktop is unchanged: dial, graph and separate cards.
await page.setViewportSize({ width: 1280, height: 900 })
await page.waitForTimeout(500)
if (await page.getByRole('tab').count()) fail('tabs shown on desktop')
await page.locator('svg[role="group"]').waitFor({ timeout: 4000 }).catch(() => fail('EQ graph missing on desktop'))
await b.close()
if (!process.exitCode) console.log('speaker-phone e2e: ok')
