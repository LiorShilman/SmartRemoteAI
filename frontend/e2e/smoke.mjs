// Smoke test: run `npm run dev` first, then `node e2e/smoke.mjs`. Uses installed Edge/Chrome.
import { chromium } from 'playwright-core'
const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const p = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage()
const errs = []
p.on('pageerror', (e) => errs.push(e.message))

// Demo mode: simulated, clearly labeled
await p.goto(base + '/box', { waitUntil: 'networkidle' })
if (!(await p.getByText('מצב הדגמה:').first().isVisible())) fail('demo banner missing')
for (const k of ['ספרה 1', 'ספרה 2']) await p.getByRole('button', { name: k, exact: true }).click()
// instant keypad: each digit goes out the moment it is pressed (no send button), like a physical remote
await p.getByText('סימולציה: ספרה 2').waitFor({ timeout: 4000 }).catch(() => fail('no simulated toast for the digit'))

// Voice parser preview
await p.goto(base + '/voice', { waitUntil: 'networkidle' })
await p.getByLabel('פקודה בטקסט').fill('שים ערוץ 12 ואז תנמיך')
if ((await p.locator('ol li').count()) !== 2) fail('expected 2 preview steps')

// Live mode with no backend: honest offline state, no fake success
await p.goto(base + '/settings', { waitUntil: 'networkidle' })
await p.getByRole('radio', { name: 'מצב אמיתי' }).click()
await p.getByText(/אין חיבור לשרת השלט|נדרש קוד גישה תקין/).first().waitFor({ timeout: 6000 }).catch(() => fail('offline banner missing'))
await p.goto(base + '/hot', { waitUntil: 'networkidle' })
const key1 = p.getByRole('button', { name: 'ספרה 1', exact: true })
await p.getByText('טוען מכשירים').waitFor({ state: 'detached', timeout: 6000 }).catch(() => {})
// Without a working backend/token there are no devices (empty state) or the keys are disabled; never an enabled key.
if ((await key1.count()) > 0 && !(await key1.isDisabled())) fail('keys must not be usable without a working backend')

if (errs.length) fail('page errors: ' + errs.join('; '))
await b.close()
console.log(process.exitCode ? 'smoke FAILED' : 'smoke OK')
