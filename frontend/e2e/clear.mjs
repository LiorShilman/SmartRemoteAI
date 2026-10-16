// Clear / multi-select flows. Part 1 runs in demo mode (local history). Part 2 needs the real backend + ACCESS_TOKEN env.
// Run: ACCESS_TOKEN=... BASE_URL=https://host:41000/SmartRemoteAI node e2e/clear.mjs   (dev server: just BASE_URL=http://127.0.0.1:5173 and a backend)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const token = process.env.ACCESS_TOKEN
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({
  channel: process.env.BROWSER ?? 'msedge',
  args: process.env.HOST_MAP ? [`--host-resolver-rules=${process.env.HOST_MAP}`, '--ignore-certificate-errors'] : [],
})
const ctx = await b.newContext({ viewport: { width: 420, height: 900 }, ignoreHTTPSErrors: true })
const p = await ctx.newPage()

// ---- Part 1: dashboard history, demo mode (nothing leaves the browser)
await p.goto(base + '/box', { waitUntil: 'networkidle' })
for (const [i, k] of ['ספרה 1', 'ספרה 2', 'ספרה 3'].entries()) {
  await p.getByRole('button', { name: k, exact: true }).click()
  // a number is digits + OK, so it takes a moment: wait until THIS send has been recorded (not for an older toast)
  await p.waitForFunction((n) => (JSON.parse(localStorage.getItem('smart-remote-ai') || '{}').state?.log ?? []).length >= n, i + 1, { timeout: 5000 })
}
await p.goto(base + '/', { waitUntil: 'networkidle' })
const rows = () => p.locator('section:has-text("פעולות אחרונות") li').count()
if ((await rows()) < 3) fail(`expected >=3 history rows, got ${await rows()}`)
const before = await rows()
await p.getByRole('button', { name: 'בחירה מרובה' }).click()
const boxes = p.locator('section:has-text("פעולות אחרונות") input[type=checkbox]')
await boxes.nth(0).check(); await boxes.nth(1).check()
await p.getByRole('button', { name: /מחק את הנבחרים/ }).click()
if ((await rows()) !== before - 2) fail(`multi-delete: expected ${before - 2} rows, got ${await rows()}`)
// select-all then delete
await p.getByRole('button', { name: 'בחירה מרובה' }).click()
await p.getByRole('button', { name: 'בחר הכל' }).click()
await p.getByRole('button', { name: /מחק את הנבחרים/ }).click()
await p.getByText('עדיין לא נשלחו פעולות').waitFor({ timeout: 3000 }).catch(() => fail('history not empty after delete-all'))

// ---- Part 2: server-side schedules
if (!token) { console.log('part 2 skipped (no ACCESS_TOKEN)'); await b.close(); process.exit() }
await p.evaluate((t) => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: t }, version: 2 })), token)
const api = (path, method = 'GET', body) => p.evaluate(async ([base, path, method, body, t]) => {
  const r = await fetch(base + path, { method, headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  return r.status === 204 ? null : r.json()
}, [new URL(base).pathname.replace(/\/$/, ''), path, method, body, token])
const ids = []
for (const n of ['א', 'ב', 'ג']) ids.push((await api('/api/schedule', 'POST', { target: 'lg', action: 'mute', delay_seconds: 3000, label: `בדיקת ניקוי ${n}` })).id)
await p.goto(base + '/voice', { waitUntil: 'networkidle' })
const sched = p.locator('section:has-text("פעולות מתוזמנות") li')
await sched.first().waitFor({ timeout: 8000 })
await p.getByRole('button', { name: 'בחירה מרובה' }).first().click()
const srow = (n) => p.locator('section:has-text("פעולות מתוזמנות") li', { hasText: `בדיקת ניקוי ${n}` }).locator('input[type=checkbox]')
await srow('א').check(); await srow('ב').check()
await p.getByRole('button', { name: /מחק \/ בטל את הנבחרים/ }).click()
await p.waitForTimeout(800)
const left = (await api('/api/schedule')).filter((s) => ids.includes(s.id))
if (left.length !== 1 || left[0].id !== ids[2]) fail(`expected only the third schedule left, got ${JSON.stringify(left.map((s) => s.label))}`)
await api('/api/schedule/clear', 'POST', { ids: [ids[2]] }) // leave nothing behind
if ((await api('/api/schedule')).some((s) => ids.includes(s.id))) fail('cleanup left schedules behind')

await b.close()
console.log(process.exitCode ? 'clear FAILED' : 'clear OK')
