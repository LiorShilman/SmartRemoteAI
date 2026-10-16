// Live-mode smoke against a backend started with USE_MOCK_ADAPTERS=true and ACCESS_TOKEN=dev-token-xyz.
import { chromium } from 'playwright-core'
const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const p = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage()
await p.goto(base + '/settings', { waitUntil: 'networkidle' })
await p.getByRole('radio', { name: 'מצב אמיתי' }).click()
await p.locator('input[type=password]').fill('wrong')
await p.getByText('קוד גישה שגוי').first().waitFor({ timeout: 12000 }).catch(() => fail('bad token not reported'))
await p.locator('input[type=password]').fill('dev-token-xyz')
await p.getByText('השרת מחובר').waitFor({ timeout: 12000 }).catch(() => fail('not connected'))
await p.getByRole('button', { name: /^צמד / }).first().click({ timeout: 8000 }).catch(() => fail('no device to pair (add one first)'))
await p.getByRole('button', { name: 'התחל צימוד' }).click()
await p.locator('input[maxlength="8"]').fill('123456')
await p.getByRole('button', { name: 'אשר צימוד' }).click()
await p.getByText('הצימוד הושלם').waitFor({ timeout: 5000 }).catch(() => fail('pairing toast missing'))
await p.goto(base + '/hot', { waitUntil: 'networkidle' })
await p.getByRole('button', { name: 'אישור', exact: true }).click()
await p.getByText('נשלח: אישור').waitFor({ timeout: 5000 }).catch(() => fail('sent toast missing'))
await b.close()
console.log(process.exitCode ? 'live FAILED' : 'live OK')
