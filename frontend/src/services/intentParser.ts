import type { Command, DeviceKind } from '../types'

export interface ParsedStep {
  command: Command
  /** Hebrew description shown in the preview before anything is executed. */
  label: string
}
export interface ParseResult {
  steps: ParsedStep[]
  /** Parts of the sentence we could not map to a supported command. */
  unrecognized: string[]
}

interface Options { volumeTarget: DeviceKind }

// JS \b is ASCII-only, so Hebrew connectors are delimited by whitespace instead.
const SPLIT = /\s*[,.]\s*|\s+(?:ואז|ואחר כך|אחרי זה)\s+/u

function normalize(s: string): string {
  return s
    .toLowerCase()
    .replace(/[״"׳']/gu, '')
    .replace(/[֑-ׇ]/gu, '')
    .replace(/\s+/gu, ' ')
    .trim()
}

function parseOne(raw: string, opts: Options): ParsedStep | null {
  const t = normalize(raw)
  if (!t) return null

  let m = t.match(/(?:^|\s)(?:ערוץ|תעבור לערוץ|עבור לערוץ|שים ערוץ|שים על ערוץ)\s*(\d{1,3})$/u)
  if (m) {
    return {
      command: { target: 'hot', action: 'digits', params: { digits: m[1] } },
      label: `ממיר: מעבר לערוץ ${m[1]} (ניסיוני)`,
    }
  }

  m = t.match(/hdmi\s*(\d)/iu)
  if (m && /(?:החלף|עבור|תעבור|שנה|עבר|מעבר|הצג|^hdmi)/u.test(t)) {
    return {
      command: { target: 'lg', action: 'set_input', params: { input: `HDMI_${m[1]}` } },
      label: `טלוויזיה: מעבר ל-HDMI ${m[1]}`,
    }
  }

  const vt = opts.volumeTarget
  const vname = vt === 'lg' ? 'טלוויזיה' : 'ממיר'
  if (/^(?:תגביר|הגבר|תעלה|העלה|יותר חזק|חזק יותר)(?:\s|$)/u.test(t))
    return { command: { target: vt, action: 'volume_up' }, label: `${vname}: הגברת עוצמה` }
  if (/^(?:תנמיך|הנמך|תוריד|הורד|יותר חלש|חלש יותר|יותר שקט)(?:\s|$)/u.test(t))
    return { command: { target: vt, action: 'volume_down' }, label: `${vname}: הנמכת עוצמה` }
  if (/^(?:תשתיק|השתק|שתק|מיוט|mute)(?:\s|$)/u.test(t))
    return { command: { target: vt, action: 'mute' }, label: `${vname}: השתקה` }

  m = t.match(/^(?:פתח|תפתח|הפעל)\s+(יוטיוב|נטפליקס|ספוטיפיי|ספוטיפי)(?:\s+(?:ב|על|ב-)\s*(ממיר|הממיר|טלוויזיה|הטלוויזיה|hot|lg))?$/u)
  if (m) {
    const app = m[1] === 'יוטיוב' ? 'youtube' : m[1] === 'נטפליקס' ? 'netflix' : 'spotify'
    const target: DeviceKind = ['ממיר', 'הממיר', 'hot'].includes(m[2] ?? '') ? 'hot' : 'lg' // default: the TV, as before
    const name = { youtube: 'YouTube', netflix: 'Netflix', spotify: 'Spotify' }[app]
    return { command: { target, action: 'launch_app', params: { app } }, label: `${target === 'hot' ? 'ממיר' : 'טלוויזיה'}: פתיחת ${name}` }
  }
  if (/^(?:כבה|תכבה)\s+(?:את\s+)?(?:הטלוויזיה|הטלויזיה|טלוויזיה|טלויזיה|הטי וי)$/u.test(t))
    return { command: { target: 'lg', action: 'power_off' }, label: 'טלוויזיה: כיבוי' }
  if (/^(?:בית|מסך הבית|לך הביתה)$/u.test(t))
    return { command: { target: 'hot', action: 'key_press', params: { key: 'HOME' } }, label: 'ממיר: בית' }
  if (/^(?:חזור|אחורה|תחזור)$/u.test(t))
    return { command: { target: 'hot', action: 'key_press', params: { key: 'BACK' } }, label: 'ממיר: חזור' }

  return null
}

export function parseIntent(text: string, opts: Options): ParseResult {
  const parts = text.split(SPLIT).map((p) => p.trim()).filter(Boolean)
  const steps: ParsedStep[] = []
  const unrecognized: string[] = []
  for (const part of parts) {
    const step = parseOne(part, opts) ?? (/^ו./u.test(part) ? parseOne(part.slice(1), opts) : null) // "ותנמיך"
    if (step) steps.push(step)
    else unrecognized.push(part)
  }
  return { steps, unrecognized }
}

/** Commands that cut power or are otherwise surprising must be confirmed explicitly. */
export function needsConfirmation(c: Command): boolean {
  return c.action === 'power_off'
}
