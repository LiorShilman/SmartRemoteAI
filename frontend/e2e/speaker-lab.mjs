// Zeppelin test lab, UI behaviour only. Every /api call is answered here (mimicking the server's rules): no backend and
// no speaker are contacted. Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-lab.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 520, height: 2400 } })).newPage()

const orig = { bass: 0, brightness: 40, rgb: { red: 255, green: 6, blue: 126 }, eq_enabled: true, loudness: false, balance: 0 }
const gain = [{ name: 'All', value: 0, min: -60, max: 20 }]
let current = structuredClone(orig)
let snapshot = null
const last = {}
const observations = []
const posts = []
const lab = () => ({ host: '192.168.1.52', snapshot, current, errors: {}, source_gain: gain, last, observations })

await page.route('**/api/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const m = req.method()
  if (m !== 'GET') posts.push({ m, path, body: req.postData() ? JSON.parse(req.postData()) : null })
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/speaker' && m === 'GET') return json({ host: '192.168.1.52', reachable: true, volume: 23, treble: 5, light: true, errors: {} })
  if (path === '/api/speaker/lab' && m === 'GET') return json(lab())
  if (path === '/api/speaker/lab/snapshot' && m === 'POST') {
    if (snapshot) { // complete an older snapshot: add only what is missing, never overwrite
      const add = Object.keys(current).filter((k) => !(k in snapshot.values))
      if (!add.length) return json({ detail: { code: 'DENIED', message: 'כבר שמורים' } }, 409)
      for (const k of add) snapshot.values[k] = structuredClone(current[k])
      return json(lab())
    }
    snapshot = { host: '192.168.1.52', at: Date.now() / 1000, values: structuredClone(current) }
    return json(lab())
  }
  if (path === '/api/speaker/lab/snapshot' && m === 'DELETE') { snapshot = null; return json(lab()) }
  if (path === '/api/speaker/lab/restore') {
    current = structuredClone(snapshot.values); snapshot = null
    return json({ restored: true, results: {}, ...lab() })
  }
  if (path === '/api/speaker/lab/observation') {
    const body = JSON.parse(req.postData())
    observations.unshift({ ...body, note: null, sent: last[body.control].sent, after: last[body.control].after, speaker_error: null, at: Date.now() / 1000, who: 'מנהל' })
    return json(lab())
  }
  const t = path.match(/^\/api\/speaker\/lab\/(bass|brightness|rgb|eq_enabled|loudness|balance)$/)
  if (t) {
    if (!snapshot) return json({ detail: { code: 'DENIED', message: 'קודם שמור את הערכים המקוריים' } }, 409)
    const c = t[1]; const body = JSON.parse(req.postData())
    const sent = c === 'rgb' ? body : body.value
    const before = structuredClone(current[c])
    current[c] = c === 'brightness' ? Math.min(sent, 100) : sent // brightness: a speaker that caps at 100
    last[c] = { control: c, sent, before, after: current[c], speaker_error: null, stored: JSON.stringify(current[c]) === JSON.stringify(sent), at: Date.now() / 1000 }
    return json(lab())
  }
  return json([])
})

await page.goto(base + '/settings', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true }, version: 4 })))
await page.goto(base + '/settings', { waitUntil: 'networkidle' })

// 1. Opening the lab only reads.
await page.getByText('בדיקת פקדים ניסיוניים ברמקול').waitFor({ timeout: 10000 }).catch(() => fail('lab card missing'))
await page.waitForTimeout(1500)
if (posts.length) fail(`writes on load: ${JSON.stringify(posts)}`)

// 2. No test before the originals are saved; the input starts at the speaker's value, so nothing differs.
const bassInput = page.getByLabel('באס לבדיקה')
if ((await bassInput.inputValue()) !== '0') fail('bass input does not start at the speaker value')
await bassInput.fill('2')
if (!(await page.getByRole('button', { name: 'שלח בדיקת באס' }).isDisabled())) fail('test allowed before saving originals')

// 3. Save originals.
await page.getByRole('button', { name: 'קרא ושמור ערכים מקוריים' }).click()
await page.getByText('הערכים המקוריים נשמרו').first().waitFor({ timeout: 5000 }).catch(() => fail('snapshot not confirmed'))
if (!snapshot) fail('snapshot not requested')

// 4. Bass test -> result shown honestly -> record what was heard.
await page.getByRole('button', { name: 'שלח בדיקת באס' }).click()
await page.getByText('הרמקול שמר את הערך (לא מוכיח שינוי בפועל)').waitFor({ timeout: 5000 }).catch(() => fail('bass result missing'))
const bassPost = posts.find((p) => p.path === '/api/speaker/lab/bass')
if (!bassPost || bassPost.body.value !== 2) fail(`bass post: ${JSON.stringify(bassPost)}`)
await page.getByRole('button', { name: 'באס: לא השתנה דבר' }).click()
await page.getByText('התצפית לבדיקה הזו נרשמה.').waitFor({ timeout: 5000 }).catch(() => fail('observation not recorded'))
if (observations[0]?.result !== 'no_change') fail('wrong observation sent')

// 5. Brightness beyond what the speaker keeps: shown as "stored a different value", not as success, not blocked by us.
await page.getByLabel('בהירות התאורה לבדיקה').fill('500')
await page.getByRole('button', { name: 'שלח בדיקת בהירות התאורה' }).click()
await page.getByText('הרמקול שמר ערך אחר מזה שנשלח').waitFor({ timeout: 5000 }).catch(() => fail('capped value not reported'))

// 6. Colour test sends the three channels.
await page.getByLabel('צבע לבדיקה').fill('#00ff80')
await page.getByRole('button', { name: 'שלח בדיקת צבע התאורה' }).click()
await page.waitForTimeout(600)
const rgbPost = posts.find((p) => p.path === '/api/speaker/lab/rgb')
if (!rgbPost || rgbPost.body.red !== 0 || rgbPost.body.green !== 255 || rgbPost.body.blue !== 128) fail(`rgb post: ${JSON.stringify(rgbPost)}`)

// 6b. Loudness (on/off) and balance (any number, "מרכז" sends 0, no left/right words); source gain read only.
await page.getByRole('button', { name: 'שלח בדיקת Loudness' }).click()
await page.waitForTimeout(500)
const lp = posts.filter((p) => p.path === '/api/speaker/lab/loudness')
if (lp.length !== 1 || lp[0].body.value !== true) fail(`loudness post: ${JSON.stringify(lp)}`)
await page.getByLabel('איזון לבדיקה').fill('6')
await page.getByRole('button', { name: 'שלח בדיקת איזון' }).click()
await page.waitForTimeout(500)
await page.getByRole('button', { name: 'מרכז את האיזון (שולח 0)' }).click()
await page.waitForTimeout(500)
const bp = posts.filter((p) => p.path === '/api/speaker/lab/balance').map((p) => p.body.value)
if (JSON.stringify(bp) !== JSON.stringify([6, 0])) fail(`balance posts: ${JSON.stringify(bp)}`)
const card = await page.locator('section', { hasText: 'בדיקת פקדים ניסיוניים ברמקול' }).innerText()
if (/ימין|שמאל/.test(card)) fail('balance shows left/right words')
await page.getByText('Source Gain').waitFor({ timeout: 3000 }).catch(() => fail('source gain status missing'))
const gainBox = await page.getByText('הרמקול מסרב לשנות את הערך הזה').locator('..').innerText()
if (!gainBox.includes('All') || !/-60\s*…\s*20/.test(gainBox)) fail(`source gain values: ${gainBox}`)
if (/dB/i.test(gainBox)) fail('source gain shows unverified units')
if (await page.getByRole('button', { name: /Source Gain/ }).count()) fail('source gain has a control')

// 7. Restore.
await page.getByRole('button', { name: 'שחזר ערכים מקוריים' }).click()
await page.getByText('הערכים המקוריים שוחזרו ואומתו מול הרמקול').waitFor({ timeout: 5000 }).catch(() => fail('restore not confirmed'))
if (JSON.stringify(current) !== JSON.stringify(orig) || snapshot) fail('restore did not bring the originals back')

// 8. A snapshot from before the new controls existed is completed, adding only what is missing.
snapshot = { host: '192.168.1.52', at: Date.now() / 1000, values: { bass: -3, brightness: 40, rgb: { red: 255, green: 6, blue: 126 } } }
await page.reload({ waitUntil: 'networkidle' })
if (!(await page.getByRole('button', { name: 'שלח בדיקת Loudness' }).isDisabled())) fail('loudness test allowed without its original saved')
await page.getByRole('button', { name: 'השלם שמירה' }).click()
await page.getByText('השמירה הושלמה').first().waitFor({ timeout: 5000 }).catch(() => fail('completion not confirmed'))
if (snapshot.values.bass !== -3 || snapshot.values.loudness === undefined || snapshot.values.balance === undefined) fail(`completion: ${JSON.stringify(snapshot.values)}`)
if (await page.getByRole('button', { name: 'השלם שמירה' }).count()) fail('completion still offered after completing')

await page.locator('section', { hasText: 'בדיקת פקדים ניסיוניים ברמקול' }).screenshot({ path: process.env.SHOT ?? 'speaker-lab.png' })
await b.close()
console.log(process.exitCode ? 'speaker lab e2e: FAILED' : 'speaker lab e2e: OK')
