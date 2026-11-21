// Speaker profiles card, UI behaviour only. Every /api call is answered here (mimicking the server): no backend and no
// speaker are contacted. Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-profiles.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 1280, height: 1800 } })).newPage()

const BANDS = ['60', '250', '1000', '3500', '12000']
let speaker = { host: '192.168.1.52', reachable: true, volume: 30, treble: 6, light: true, bass: 2, brightness: 100, rgb: { red: 24, green: 69, blue: 129 }, mute: false, loudness: true, balance: 0, errors: {} }
let eq = BANDS.map((band) => ({ min: -6, max: 6, band, step: 0.5, value: 0 }))
const cycle = { config: { interval_s: 10, mode: 'random', smooth: false, palette: [] }, status: { running: false, state: 'stopped', message: null, last_colour: null, changed_at: null, steps: 0 } }
const capture = (withVolume) => ({ eq: Object.fromEntries(eq.map((x) => [x.band, x.value])), bass: speaker.bass, treble: speaker.treble, loudness: speaker.loudness,
  rgb: speaker.rgb, brightness: speaker.brightness, cycle: { running: cycle.status.running, config: cycle.config }, ...(withVolume ? { volume: speaker.volume } : {}) })
let state = { profiles: [], loaded_id: null, undo: null, loading: false }
let nextPartial = false
const posts = []

await page.route('**/api/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const m = req.method()
  const body = req.postData() ? JSON.parse(req.postData()) : null
  if (m !== 'GET') posts.push({ m, path, body })
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/usage') return json({ today_min: 0, days: [{ day: '2026-11-15', total_min: 0, apps: {} }] })
  if (path === '/api/speaker') return json(speaker)
  if (path === '/api/speaker/eq') return json({ bands: eq, enabled: true, errors: {} })
  if (path === '/api/speaker/cycle') return json(cycle)
  if (path === '/api/speaker/profiles' && m === 'GET') return json(state)
  if (path === '/api/speaker/profiles' && m === 'POST') {
    if (state.profiles.some((p) => p.name === body.name)) return json({ detail: { code: 'INVALID_COMMAND', message: 'כבר יש פרופיל בשם הזה.' } }, 409)
    const p = { id: 'p' + (state.profiles.length + 1), name: body.name, include_volume: body.include_volume, data: capture(body.include_volume), created_at: Date.now() / 1000, updated_at: Date.now() / 1000 }
    state = { ...state, profiles: [...state.profiles, p], loaded_id: p.id }
    return json({ created: p, ...state }, 201)
  }
  const one = path.match(/^\/api\/speaker\/profiles\/(p\d+)$/)
  if (one && m === 'PATCH') { state = { ...state, profiles: state.profiles.map((p) => (p.id === one[1] ? { ...p, name: body.name } : p)) }; return json(state) }
  if (one && m === 'DELETE') { state = { ...state, profiles: state.profiles.filter((p) => p.id !== one[1]) }; return json(state) }
  const up = path.match(/^\/api\/speaker\/profiles\/(p\d+)\/update$/)
  if (up) {
    state = { ...state, loaded_id: up[1], profiles: state.profiles.map((p) => (p.id === up[1] ? { ...p, data: capture(p.include_volume), updated_at: Date.now() / 1000 } : p)) }
    return json({ updated: state.profiles.find((p) => p.id === up[1]), ...state })
  }
  const ld = path.match(/^\/api\/speaker\/profiles\/(p\d+)\/load$/)
  if (ld) {
    const p = state.profiles.find((x) => x.id === ld[1])
    const before = capture(p.include_volume)
    const steps = ['cycle_stop', 'eq', 'bass', 'treble', 'loudness', 'brightness', 'rgb', 'cycle_config'].map((s) => ({ step: s, label: s, ok: true, error: null }))
    if (nextPartial) { steps[3] = { step: 'treble', label: 'גבוהים', ok: false, error: 'Setting is not modifiable' }; nextPartial = false }
    eq = eq.map((x) => ({ ...x, value: p.data.eq[x.band] }))
    speaker = { ...speaker, bass: p.data.bass, loudness: p.data.loudness, brightness: p.data.brightness, rgb: p.data.rgb, ...(steps[3].ok ? { treble: p.data.treble } : {}) }
    const full = steps.every((s) => s.ok)
    state = { ...state, loaded_id: full ? p.id : null, undo: { at: Date.now() / 1000, from_profile: p.name, _data: before } }
    return json({ status: full ? 'full' : 'partial', steps, ...state })
  }
  if (path === '/api/speaker/profiles/undo') {
    const d = state.undo._data
    eq = eq.map((x) => ({ ...x, value: d.eq[x.band] }))
    speaker = { ...speaker, bass: d.bass, treble: d.treble, loudness: d.loudness, brightness: d.brightness, rgb: d.rgb }
    state = { ...state, undo: null, loaded_id: null }
    return json({ status: 'full', steps: [{ step: 'eq', label: 'אקולייזר', ok: true, error: null }], ...state })
  }
  if (m !== 'GET') return json({ detail: { code: 'INVALID_COMMAND', message: 'unexpected ' + path } }, 400)
  return json([])
})

await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true }, version: 4 })))
await page.goto(base + '/', { waitUntil: 'networkidle' })
const card = page.locator('section', { hasText: 'פרופילים' }).filter({ has: page.getByLabel('שם לפרופיל חדש') })
const list = card.getByRole('list', { name: 'פרופילים שמורים' })

// 1. Opening the screen loads nothing.
await card.waitFor({ timeout: 10000 }).catch(() => fail('profiles card missing'))
await page.waitForTimeout(1200)
if (posts.length) fail(`writes on load: ${JSON.stringify(posts)}`)
// placed under the EQ (same column)
const eqBox = await page.locator('section', { hasText: 'חמישה תחומים' }).boundingBox(), prBox = await card.boundingBox()
if (!(Math.abs(eqBox.x - prBox.x) < 4 && prBox.y > eqBox.y)) fail('profiles card is not under the EQ')

// 2. Save the current state (without volume), and one with volume.
await card.getByLabel('שם לפרופיל חדש').fill('ערב')
await card.getByRole('button', { name: 'שמור מצב נוכחי' }).click()
await list.getByText('ערב', { exact: true }).waitFor({ timeout: 4000 }).catch(() => fail('saved profile not listed'))
const saved = posts.find((p) => p.path === '/api/speaker/profiles')
if (saved?.body?.include_volume !== false) fail('volume included without being chosen')
await card.getByText('· תואם').waitFor({ timeout: 3000 }).catch(() => fail('"matches" chip missing after saving'))
await card.getByLabel('שם לפרופיל חדש').fill('בוקר')
await card.getByLabel('כולל עוצמה').check()
await card.getByRole('button', { name: 'שמור מצב נוכחי' }).click()
await card.getByText(/כולל עוצמה 30/).waitFor({ timeout: 4000 }).catch(() => fail('volume badge missing'))

// 3. Changing the speaker after loading shows "changed".
await card.getByRole('button', { name: 'טען את הפרופיל ערב' }).click()
await card.getByText('נטען במלואו ונקרא בחזרה מהרמקול.').waitFor({ timeout: 4000 }).catch(() => fail('full load not reported'))
speaker = { ...speaker, bass: -3 }
await page.getByRole('button', { name: 'רענן את מצב הרמקול' }).click()
await card.getByText('· שונה').waitFor({ timeout: 4000 }).catch(() => fail('"changed" chip missing'))

// 3b. Update the loaded profile to the current state (with confirmation): it matches again, nothing written to the speaker.
const nUpd = () => posts.filter((p) => p.path.endsWith('/update')).length
await card.getByRole('button', { name: 'עדכן את ערב למצב הנוכחי' }).click()
if (nUpd()) fail('updated without confirmation')
await card.getByRole('button', { name: 'אשר עדכון ערב' }).click()
await card.getByText('· תואם').waitFor({ timeout: 4000 }).catch(() => fail('"matches" chip missing after updating'))
if (nUpd() !== 1) fail(`update calls: ${nUpd()}`)
if (state.profiles.find((p) => p.name === 'ערב').data.bass !== -3) fail('profile not updated to current values')
if (await card.getByRole('button', { name: 'עדכן את ערב למצב הנוכחי' }).count()) fail('update button still shown when matching')
if (posts.some((p) => !p.path.startsWith('/api/speaker/profiles'))) fail('speaker written outside profiles')

// 4. Undo appears after a load and restores.
await card.getByRole('button', { name: 'חזור למצב הקודם' }).waitFor({ timeout: 3000 }).catch(() => fail('undo missing after load'))
await card.getByRole('button', { name: 'חזור למצב הקודם' }).click()
await page.waitForTimeout(600)
if (!posts.some((p) => p.path === '/api/speaker/profiles/undo')) fail('undo not sent')

// 5. A partial load is shown as partial, with what failed; never as fully loaded.
nextPartial = true
await card.getByRole('button', { name: 'טען את הפרופיל ערב' }).click()
await card.getByText('נטען חלקית בלבד.').waitFor({ timeout: 4000 }).catch(() => fail('partial load not reported'))
if (await card.getByText('נטען במלואו').count()) fail('partial load shown as full')
await card.getByText(/גבוהים — Setting is not modifiable/).waitFor({ timeout: 2000 }).catch(() => fail('failed step not listed'))

// 6. Rename and delete (with confirmation).
await card.getByRole('button', { name: 'שנה את שם הפרופיל בוקר' }).click()
await card.getByLabel('שם חדש לפרופיל בוקר').fill('צהריים')
await card.getByRole('button', { name: 'שמור שם' }).click()
await list.getByText('צהריים', { exact: true }).waitFor({ timeout: 3000 }).catch(() => fail('rename not shown'))
await card.getByRole('button', { name: 'מחק את הפרופיל צהריים' }).click()
if (posts.some((p) => p.m === 'DELETE')) fail('deleted without confirmation')
await card.getByRole('button', { name: 'אשר מחיקת צהריים' }).click()
await page.waitForTimeout(500)
if (await list.getByText('צהריים', { exact: true }).count()) fail('delete not shown')

// 7. Mobile: compact, no sideways scroll.
await page.setViewportSize({ width: 390, height: 900 })
await page.waitForTimeout(300)
await page.getByRole('tab', { name: 'פרופילים' }).click() // phone: profiles are a tab inside the speaker card
await page.getByLabel('שם לפרופיל חדש').waitFor({ timeout: 3000 }).catch(() => fail('profiles tab missing on mobile'))
if (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) > 0) fail('profiles card scrolls sideways on mobile')
await page.getByRole('tabpanel').screenshot({ path: process.env.SHOT ?? 'speaker-profiles.png' })
await b.close()
console.log(process.exitCode ? 'speaker profiles e2e: FAILED' : 'speaker profiles e2e: OK')
