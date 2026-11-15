// Speaker page reachable from the navigation (sidebar on desktop, bottom bar on mobile). All /api calls mocked; nothing is written.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/speaker-page.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 1280, height: 1000 } })).newPage()
const writes = []
const BANDS = ['60', '250', '1000', '3500', '12000']
await page.route('**/api/**', async (route) => {
  const req = route.request(), path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  if (req.method() !== 'GET') writes.push(path)
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/usage') return json({ today_min: 0, days: [{ day: '2026-11-15', total_min: 0, apps: {} }] })
  if (path === '/api/speaker') return json({ host: '192.168.1.52', reachable: true, volume: 20, treble: 0, light: true, bass: 0, brightness: 50, rgb: { red: 0, green: 0, blue: 255 }, mute: false, loudness: false, balance: 0, errors: {} })
  if (path === '/api/speaker/eq') return json({ bands: BANDS.map((band) => ({ band, min: -6, max: 6, step: 0.5, value: 0 })), enabled: true, errors: {} })
  if (path === '/api/speaker/cycle') return json({ config: { interval_s: 10, mode: 'random', smooth: false, palette: [] }, status: { running: false, state: 'stopped', message: null, last_colour: null, changed_at: null, steps: 0 } })
  if (path === '/api/speaker/profiles') return json({ profiles: [], loaded_id: null, undo: null, loading: false })
  return json([])
})
await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true }, version: 4 })))
await page.goto(base + '/', { waitUntil: 'networkidle' })

for (const [w, h] of [[1280, 1000], [390, 860]]) {
  await page.setViewportSize({ width: w, height: h })
  await page.goto(base + '/', { waitUntil: 'networkidle' })
  const link = page.getByRole('link', { name: 'רמקול', exact: true }).filter({ visible: true }).first()
  await link.click({ timeout: 5000 }).catch(() => fail(`no "רמקול" in the navigation at ${w}px`))
  await page.waitForURL(/\/speaker$/, { timeout: 3000 }).catch(() => fail('did not navigate to /speaker'))
  await page.getByRole('heading', { name: 'רמקול', level: 1 }).waitFor({ timeout: 5000 }).catch(() => fail('speaker page heading missing'))
  if (await page.getByText('מפת חיבורים').count()) fail('home screen still shown on /speaker')
  await page.waitForTimeout(600)
  await page.getByRole('slider', { name: 'עוצמה' }).waitFor({ timeout: 5000 }).catch(() => fail(`speaker card missing at ${w}px`))
  await page.getByText('חמישה תחומים').waitFor({ timeout: 3000 }).catch(() => fail('EQ missing'))
  await page.getByLabel('שם לפרופיל חדש').waitFor({ timeout: 3000 }).catch(() => fail('profiles missing'))
  if (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) > 0) fail(`sideways scroll at ${w}px`)
  await page.screenshot({ path: (process.env.SHOT ?? 'speaker-page') + `-${w}.png`, fullPage: true })
}
if (writes.length) fail(`writes while opening the page: ${writes}`)
await b.close()
console.log(process.exitCode ? 'speaker page e2e: FAILED' : 'speaker page e2e: OK')
