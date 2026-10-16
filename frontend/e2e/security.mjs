// Per-device access codes end to end, through the UI of the real deployment:
// create a code -> use its login link in a fresh browser -> limited to day-to-day use -> revoke -> that browser is locked out.
// Run: ACCESS_TOKEN=<master> BASE_URL=https://host:41000/SmartRemoteAI [HOST_MAP="MAP host 127.0.0.1"] node e2e/security.mjs
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL
const master = process.env.ACCESS_TOKEN
if (!base || !master) { console.error('BASE_URL and ACCESS_TOKEN are required'); process.exit(2) }
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({
  channel: process.env.BROWSER ?? 'msedge',
  args: process.env.HOST_MAP ? [`--host-resolver-rules=${process.env.HOST_MAP}`, '--ignore-certificate-errors'] : [],
})
const mk = async () => { const c = await b.newContext({ viewport: { width: 420, height: 1000 }, ignoreHTTPSErrors: true }); return [c, await c.newPage()] }

// ---- admin creates a code
const [, admin] = await mk()
await admin.goto(base + '/settings', { waitUntil: 'networkidle' })
await admin.evaluate((t) => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: t }, version: 2 })), master)
await admin.goto(base + '/settings', { waitUntil: 'networkidle' })
await admin.getByText('קודי גישה למכשירים').waitFor({ timeout: 10000 }).catch(() => fail('security card missing for admin'))
const name = `בדיקה-${Date.now() % 100000}`
await admin.getByLabel('שם הקוד החדש').fill(name)
await admin.getByRole('button', { name: 'צור קוד' }).click()
const secret = await admin.getByLabel('הקוד החדש', { exact: true }).inputValue({ timeout: 8000 }).catch(() => '')
if (!secret.startsWith('sr_')) fail(`no new code shown (${secret})`)

// ---- the new code works through the login link, and is limited to day-to-day use
const [, phone] = await mk()
await phone.goto(`${base}/#token=${encodeURIComponent(secret)}`, { waitUntil: 'networkidle' })
if (new URL(phone.url()).hash) fail('login fragment was not removed from the address bar')
await phone.goto(base + '/settings', { waitUntil: 'networkidle' })
await phone.getByText('השרת מחובר').waitFor({ timeout: 10000 }).catch(() => fail('device code not accepted'))
await phone.getByText('גישה למכשיר זה בלבד').waitFor({ timeout: 8000 }).catch(() => fail('"device only" label missing'))
if (await phone.getByText('קודי גישה למכשירים').count()) fail('device code must not see access management')
if (await phone.getByText('יומן פעילות').count()) fail('device code must not see the audit log')
if (await phone.getByRole('button', { name: 'סרוק את הרשת' }).count()) fail('device code must not see network scan')
await phone.goto(base + '/', { waitUntil: 'networkidle' })
await phone.getByText('מפת חיבורים').waitFor({ timeout: 8000 }).catch(() => fail('device code cannot use the dashboard'))

// ---- revoke -> the phone is locked out
await admin.getByRole('button', { name: `בטל את הקוד של ${name}` }).click()
await admin.getByRole('button', { name: `אשר ביטול ${name}` }).click()
await admin.getByText('בוטל').first().waitFor({ timeout: 8000 }).catch(() => fail('revocation not shown'))
await phone.reload({ waitUntil: 'networkidle' })
await phone.goto(base + '/settings', { waitUntil: 'networkidle' })
await phone.getByText(/קוד גישה שגוי|נדרש קוד גישה/).first().waitFor({ timeout: 15000 }).catch(() => fail('revoked code still accepted'))

// ---- the audit log shows what happened, without any secret
await admin.reload({ waitUntil: 'networkidle' })
await admin.getByText('יומן פעילות').waitFor({ timeout: 10000 })
await admin.getByText('נוצר קוד גישה').first().waitFor({ timeout: 8000 }).catch(() => fail('audit: token_created missing'))
if ((await admin.locator('body').innerText()).includes(secret)) fail('the secret leaked into the page after creation')

// tidy up: remove the revoked test code from the list through the real UI (select it, remove)
await admin.getByRole('button', { name: 'בחירה מרובה' }).first().click()
await admin.locator('li', { hasText: name }).locator('input[type=checkbox]').check()
await admin.getByRole('button', { name: /הסר את הנבחרים/ }).click()
await admin.waitForTimeout(800)
// (the audit log legitimately still mentions the name, so look only inside the access-codes card)
if ((await admin.locator('section:has-text("קודי גישה למכשירים")').innerText()).includes(name)) fail('revoked test code was not removed from the list')

await b.close()
console.log(process.exitCode ? 'security FAILED' : 'security OK')
