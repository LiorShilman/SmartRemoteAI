// Kids mode end to end, in the browser, against a real deployment (create a restricted code -> it is blocked by the
// server outside its hours -> the kid asks for more time -> the parent approves -> clean up).
// Run: ACCESS_TOKEN=<master> BASE_URL=https://host:41000/SmartRemoteAI [HOST_MAP="MAP host 127.0.0.1"] node e2e/kids.mjs
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL
const master = process.env.ACCESS_TOKEN
if (!base || !master) { console.error('BASE_URL and ACCESS_TOKEN are required'); process.exit(2) }
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({
  channel: process.env.BROWSER ?? 'msedge',
  args: process.env.HOST_MAP ? [`--host-resolver-rules=${process.env.HOST_MAP}`, '--ignore-certificate-errors'] : [],
})
const mk = async () => { const c = await b.newContext({ viewport: { width: 440, height: 1000 }, ignoreHTTPSErrors: true }); return [c, await c.newPage()] }

// ---- parent: create a restricted code whose allowed window (00:00-00:01) is closed right now
const [, parent] = await mk()
await parent.goto(base + '/settings', { waitUntil: 'networkidle' })
await parent.evaluate((t) => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: t }, version: 4 })), master)
await parent.goto(base + '/settings', { waitUntil: 'networkidle' })
await parent.getByText('קודי גישה למכשירים').waitFor({ timeout: 10000 })
const name = `ילד-${Date.now() % 100000}`
await parent.getByLabel('שם הקוד החדש').fill(name)
await parent.getByLabel(/מצב ילדים \(הגבלות/).check()
await parent.locator('input[type=time]').nth(0).fill('00:00')
await parent.locator('input[type=time]').nth(1).fill('00:01')
await parent.getByRole('button', { name: 'צור קוד' }).click()
const secret = await parent.getByLabel('הקוד החדש', { exact: true }).inputValue({ timeout: 8000 }).catch(() => '')
if (!secret.startsWith('sr_')) fail('no code was created')

// ---- kid: signs in with the link, sees the banner, and the server refuses everything
const [, kid] = await mk()
await kid.goto(`${base}/#token=${encodeURIComponent(secret)}`, { waitUntil: 'networkidle' })
await kid.goto(base + '/box', { waitUntil: 'networkidle' })
await kid.getByText(/מחוץ לשעות המותרות \(00:00–00:01\)/).first().waitFor({ timeout: 12000 }).catch(() => fail('kid banner (outside hours) missing'))
await kid.getByRole('button', { name: 'אישור', exact: true }).first().click().catch(() => fail('cannot press OK'))
await kid.getByText(/מחוץ לשעות המותרות/).nth(1).waitFor({ timeout: 6000 }).catch(() => fail('server refusal was not shown to the kid'))
if (await kid.getByRole('button', { name: 'סרוק את הרשת' }).count()) fail('kid sees admin tools')

// ---- kid asks for 15 minutes
await kid.getByRole('button', { name: 'בקש עוד זמן', exact: true }).click({ timeout: 10000 }).catch((e) => { console.log('CLICK ERROR:', String(e.message).replace(/\s+/g, ' ').slice(0, 400)); fail('ask button not available') })
await kid.getByRole('button', { name: 'בקש 15 דקות', exact: true }).click()
await kid.getByText('הבקשה נשלחה, ממתינים לאישור').waitFor({ timeout: 8000 }).catch(() => fail('pending state missing'))

// ---- parent sees the request (and the red dot), approves it
await parent.reload({ waitUntil: 'networkidle' })
await parent.getByText(/בקשות לעוד זמן \(1\)/).waitFor({ timeout: 12000 }).catch(() => fail('parent does not see the request'))
if ((await parent.locator('[aria-label$="בקשות זמן ממתינות"]').count()) === 0) fail('no red dot on the settings tab')
await parent.getByRole('button', { name: new RegExp(`אשר 15 דקות ל${name}`) }).click()
await parent.getByText(/בקשות לעוד זמן/).waitFor({ state: 'detached', timeout: 8000 }).catch(() => fail('request still pending after approval'))

// ---- kid sees the decision (window still closed: the extra time only extends the END of the window)
await kid.reload({ waitUntil: 'networkidle' })
await kid.getByText('(+15 דק׳ שאושרו)').waitFor({ timeout: 15000 }).catch(() => fail('kid does not see the approved minutes'))
await kid.getByText('אושר עוד זמן').first().waitFor({ timeout: 5000 }).catch(() => fail('approved chip missing'))

// ---- the parent's dashboard shows screen time; the audit log recorded the story
await parent.goto(base + '/', { waitUntil: 'networkidle' })
await parent.getByText('זמן מסך').first().waitFor({ timeout: 8000 }).catch(() => fail('screen-time card missing for the parent'))
await parent.goto(base + '/settings', { waitUntil: 'networkidle' })
for (const t of ['פעולה נחסמה (מצב ילדים)', 'אושר עוד זמן', 'התבקש עוד זמן']) {
  await parent.getByText(t).first().waitFor({ timeout: 8000 }).catch(() => fail(`audit missing: ${t}`))
}

// ---- clean up: revoke the code and remove it from the list
await parent.getByRole('button', { name: `בטל את הקוד של ${name}` }).click()
await parent.getByRole('button', { name: `אשר ביטול ${name}` }).click()
await parent.getByRole('button', { name: 'בחירה מרובה' }).first().click()
await parent.locator('li', { hasText: name }).locator('input[type=checkbox]').check()
await parent.getByRole('button', { name: /הסר את הנבחרים/ }).click()
await parent.waitForTimeout(800)
if ((await parent.locator('section:has-text("קודי גישה למכשירים")').innerText()).includes(name)) fail('test code left behind')

await b.close()
console.log(process.exitCode ? 'kids FAILED' : 'kids OK')
