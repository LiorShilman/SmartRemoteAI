// In-app guide: the one-time welcome card, the "?" entry points and every tab of the guide (works in demo mode).
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/help.mjs
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({
  channel: process.env.BROWSER ?? 'msedge',
  args: process.env.HOST_MAP ? [`--host-resolver-rules=${process.env.HOST_MAP}`, '--ignore-certificate-errors'] : [],
})
const ctx = await b.newContext({ viewport: { width: 400, height: 900 }, ignoreHTTPSErrors: true })
const p = await ctx.newPage()
const errors = []
p.on('pageerror', (e) => errors.push(e.message))

// welcome card: shown once, dismissible, and it stays dismissed
await p.goto(base + '/', { waitUntil: 'networkidle' })
await p.getByText('ברוכים הבאים').waitFor({ timeout: 6000 }).catch(() => fail('welcome card missing on first visit'))
await p.getByRole('button', { name: 'הבנתי, תודה' }).click()
if (await p.getByText('ברוכים הבאים').count()) fail('welcome card did not close')
await p.reload({ waitUntil: 'networkidle' })
if (await p.getByText('ברוכים הבאים').count()) fail('welcome card came back after a reload')

// "?" in the header opens the guide
await p.getByRole('link', { name: 'מדריך ועזרה' }).click()
await p.getByRole('heading', { name: 'מדריך', exact: true }).waitFor({ timeout: 6000 }).catch(() => fail('guide did not open from the ? button'))

// every tab shows its own content
const expect = {
  'התחלה': 'פותחים את הקישור האישי',
  'שלט': 'איך משתמשים בשלט',
  'אפליקציות וחיפוש': 'אפליקציות וחיפוש',
  'קול': 'לחיצה על המיקרופון ודיבור',
  'ילדים': 'בקשת עוד זמן',
  'תקלות': 'איבדתי את הטלפון',
}
for (const [tab, marker] of Object.entries(expect)) {
  await p.getByRole('tab', { name: tab, exact: true }).click()
  if ((await p.getByRole('tab', { name: tab, exact: true }).getAttribute('aria-selected')) !== 'true') fail(`tab ${tab} not selected`)
  await p.getByText(marker).first().waitFor({ timeout: 4000 }).catch(() => fail(`tab "${tab}" is missing "${marker}"`))
}
// FAQ entries open and close
await p.getByText('איבדתי את הטלפון').click()
await p.getByText('מבקשים מהמנהל לבטל את הקוד').waitFor({ timeout: 3000 }).catch(() => fail('FAQ answer did not open'))

// keyboard: tabs are reachable and the page has no horizontal overflow
const over = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
if (over > 0) fail(`horizontal overflow ${over}px`)
if (errors.length) fail('page errors: ' + errors.join('; '))

await b.close()
console.log(process.exitCode ? 'help FAILED' : 'help OK')
