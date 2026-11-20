// Voice page -> speaker steps, UI behaviour only. Every /api call is answered here: no backend, no speaker.
// Run: BASE_URL=http://127.0.0.1:5173 node e2e/voice-speaker.mjs   (with `npm run dev` running)
import { chromium } from 'playwright-core'

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5173'
const fail = (m) => { console.error('FAIL:', m); process.exitCode = 1 }
const b = await chromium.launch({ channel: process.env.BROWSER ?? 'msedge' })
const page = await (await b.newContext({ viewport: { width: 420, height: 1400 } })).newPage()

let speaker = { host: '192.168.1.52', reachable: true, volume: 23, treble: 5, light: true, bass: -1, brightness: 100, rgb: { red: 255, green: 6, blue: 126 }, loudness: false, mute: false, balance: 0, errors: {} }
const steps = []
const scheduled = []
let failNext = null
const ttsTexts = [] // what the page asked the server to say
const PARSE = {
  'השתק את הרמקול': [{ target: 'speaker', action: 'speaker_mute', params: { enabled: true }, label: 'רמקול: השתקה', delay_seconds: 0 }],
  'תגביר את הרמקול ואז אור כחול': [
    { target: 'speaker', action: 'speaker_volume', params: { delta: 3 }, label: 'רמקול: הגברה (+3)', delay_seconds: 0 },
    { target: 'speaker', action: 'speaker_color', params: { color: 'כחול' }, label: 'רמקול: תאורה בצבע כחול', delay_seconds: 0 }],
  'השתק את הרמקול בעוד שעה': [{ target: 'speaker', action: 'speaker_mute', params: { enabled: true }, label: 'רמקול: השתקה (בעוד שעה)', delay_seconds: 3600 }],
}
await page.route('**/api/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname.replace(/^.*\/api/, '/api')
  const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  const body = req.postData() ? JSON.parse(req.postData()) : null
  if (path === '/api/health') return json({ ok: true, version: 'e2e' })
  if (path === '/api/me') return json({ kind: 'admin', name: 'מנהל', pending_requests: 0 })
  if (path === '/api/devices') return json([])
  if (path === '/api/speaker' && req.method() === 'GET') return json(speaker)
  if (path === '/api/tts') { ttsTexts.push(body.text); return route.fulfill({ status: 200, contentType: 'audio/mpeg', body: Buffer.from('ID3') }) }
  if (path === '/api/intents/parse') return json({ steps: PARSE[body.text] ?? [], unrecognized: PARSE[body.text] ? [] : [body.text], provider: 'rules' })
  if (path === '/api/speaker/step') {
    steps.push(body)
    if (failNext) { const f = failNext; failNext = null; return json({ detail: { code: 'DENIED', message: f } }, 502) }
    if (body.op === 'speaker_mute') speaker = { ...speaker, mute: body.params.enabled }
    if (body.op === 'speaker_volume') speaker = { ...speaker, volume: speaker.volume + body.params.delta }
    return json(speaker)
  }
  if (path === '/api/schedule' && req.method() === 'POST') {
    scheduled.push(body)
    return json({ id: 's1', run_at: Date.now() / 1000 + 3600, ...body, status: 'pending', error: null }, 201)
  }
  if (path === '/api/schedule') return json(scheduled.map((x, i) => ({ id: `s${i + 1}`, run_at: Date.now() / 1000 + 3600, ...x, status: 'pending', error: null })))
  return json([])
})

// A fake Hebrew voice: records what would be spoken (no audio, no dependency on the machine's voices).
await page.addInitScript(() => {
  window.__spoken = []
  const voice = { lang: 'he-IL', name: 'Fake Hebrew', localService: true, default: false, voiceURI: 'fake' }
  window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text } }
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
    getVoices: () => [voice], speak: (u) => window.__spoken.push(u.text), cancel: () => {},
    addEventListener: () => {}, removeEventListener: () => {} } })
  HTMLMediaElement.prototype.play = function () { return Promise.resolve() } // no audio device in tests
  // a fake microphone: the test decides what it "hears"
  window.__recs = []
  window.SpeechRecognition = class { constructor() { this.aborted = false; window.__recs.push(this) }
    start() {} stop() { this.onend?.() } abort() { this.aborted = true; this.onerror?.({ error: 'aborted' }); this.onend?.() } }
})
// Live mode: the reply is the server's voice. The browser voice is only a fallback and must stay unused here.
const spoken = async () => {
  await page.waitForTimeout(300)
  if ((await page.evaluate(() => window.__spoken.length))) fail('browser voice used although the server voice worked')
  return ttsTexts.splice(0)
}
await page.goto(base + '/', { waitUntil: 'networkidle' })
await page.evaluate(() => localStorage.setItem('smart-remote-ai', JSON.stringify({ state: { mode: 'live', token: 'e2e', introSeen: true, successToasts: true }, version: 4 })))
await page.goto(base + '/voice', { waitUntil: 'networkidle' })
const input = page.getByRole('textbox', { name: 'פקודה בטקסט' })
const runBtn = page.getByRole('button', { name: 'בצע' })

// 0. Grouped examples; pressing one only fills the box and previews.
await page.setViewportSize({ width: 1100, height: 900 })
await page.getByText('רמקול – צליל ותאורה').waitFor({ timeout: 4000 }).catch(() => fail('example groups missing'))
await page.screenshot({ path: 'voice-examples.png' })
await page.setViewportSize({ width: 420, height: 1400 })
await page.getByRole('button', { name: 'השתק את הרמקול', exact: true }).click()
if ((await input.inputValue()) !== 'השתק את הרמקול') fail('example did not fill the box')
await page.getByText('רמקול: השתקה', { exact: true }).waitFor({ timeout: 4000 }).catch(() => fail('example preview missing'))
await page.waitForTimeout(500)
if (steps.length || scheduled.length) fail('an example press sent something')
await input.fill('')

// 1. Typing only previews: nothing is sent before "בצע".
await input.fill('השתק את הרמקול')
await page.getByText('רמקול: השתקה', { exact: true }).waitFor({ timeout: 4000 }).catch(() => fail('speaker step preview missing'))
await page.waitForTimeout(500)
if (steps.length || scheduled.length) fail('sent before confirmation')
await runBtn.click()
await page.waitForTimeout(800)
if (JSON.stringify(steps) !== JSON.stringify([{ op: 'speaker_mute', params: { enabled: true } }])) fail(`mute step: ${JSON.stringify(steps)}`)
// spoken reply from the speaker's read-back, only after "בצע"
const s1 = await spoken()
if (JSON.stringify(s1) !== JSON.stringify(['הרמקול מושתק'])) fail(`spoken after mute: ${JSON.stringify(s1)}`)

// 2. Two steps in order; a failure stops the sequence and shows the server's reason.
steps.length = 0
await input.fill('תגביר את הרמקול ואז אור כחול')
await page.getByText('רמקול: תאורה בצבע כחול').waitFor({ timeout: 4000 })
failNext = 'הרמקול קיבל את הבקשה, אבל הערך לא השתנה'
await runBtn.click()
await page.getByText(/הערך לא השתנה/).first().waitFor({ timeout: 4000 }).catch(() => fail('failure reason not shown'))
if (steps.length !== 1 || steps[0].op !== 'speaker_volume') fail(`sequence continued after a failure: ${JSON.stringify(steps)}`)
const s2 = await spoken()
if (s2.length !== 1 || !s2[0].startsWith('נכשל: הגברה') || !s2[0].includes('הערך לא השתנה')) fail(`spoken after failure: ${JSON.stringify(s2)}`)

// 3. A delayed speaker step is scheduled on the server, not run now.
steps.length = 0
await input.fill('השתק את הרמקול בעוד שעה')
await page.getByText('רמקול: השתקה (בעוד שעה)').first().waitFor({ timeout: 4000 })
await page.getByRole('button', { name: 'בצע' }).click()
await page.waitForTimeout(800)
if (steps.length) fail('delayed step ran immediately')
const s3 = await spoken()
if (JSON.stringify(s3) !== JSON.stringify(['תוזמן: השתקה (בעוד שעה)'])) fail(`spoken after schedule: ${JSON.stringify(s3)}`)
if (scheduled.length !== 1 || scheduled[0].target !== 'speaker' || scheduled[0].action !== 'speaker_mute' || scheduled[0].delay_seconds !== 3600) fail(`schedule: ${JSON.stringify(scheduled)}`)

// 4. Switched off: nothing is spoken (and the choice is kept).
await page.getByRole('switch', { name: /תשובה בקול/ }).click()
steps.length = 0
await input.fill('השתק את הרמקול')
await page.getByText('רמקול: השתקה', { exact: true }).waitFor({ timeout: 4000 })
await page.getByRole('button', { name: 'בצע' }).click()
await page.waitForTimeout(800)
if (steps.length !== 1) fail('step not run with reply off')
if ((await spoken()).length) fail('spoke while switched off')
if ((await page.evaluate(() => localStorage.getItem('voice-reply'))) !== '0') fail('reply choice not kept')

// 5. The microphone never hears its own reply: "בצע" stops listening, and a late result is ignored.
await page.getByRole('switch', { name: /תשובה בקול/ }).click() // reply back on
await page.reload({ waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'התחל הקלטה' }).click()
const hear = (t) => page.evaluate((t) => { const r = window.__recs.at(-1); r.onresult?.({ results: [Object.assign([{ transcript: t }], { isFinal: true })] }) }, t)
await hear('השתק את הרמקול')
await page.getByText('רמקול: השתקה', { exact: true }).waitFor({ timeout: 4000 }).catch(() => fail('spoken command not previewed'))
steps.length = 0
await page.getByRole('button', { name: 'בצע' }).click()
await page.waitForTimeout(800)
if (!(await page.evaluate(() => window.__recs.at(-1).aborted))) fail('microphone still listening while replying')
await hear('הרמקול מושתק') // what the reply would sound like
await page.waitForTimeout(600)
if ((await page.getByRole('textbox', { name: 'פקודה בטקסט' }).inputValue()) !== '') fail('the reply was taken as a new command')
if (await page.getByText(/שגיאת זיהוי קול/).count()) fail('abort shown as an error')
await spoken()

await page.screenshot({ path: 'voice-speaker.png', fullPage: true })
await b.close()
if (!process.exitCode) console.log('voice-speaker e2e: ok')
