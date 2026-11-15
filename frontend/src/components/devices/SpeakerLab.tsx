import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, RefreshCw, RotateCcw } from 'lucide-react'
import { Card, Key, SectionTitle } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'
import type { LabControl, LabProbe, LabValue, Rgb, SourceGain, SpeakerLab as Lab } from '../../types'

const LABEL: Record<LabControl, string> = {
  bass: 'באס', brightness: 'בהירות התאורה', rgb: 'צבע התאורה', eq_enabled: 'מתג האקולייזר', loudness: 'Loudness', balance: 'איזון',
}
const CONTROLS: LabControl[] = ['bass', 'brightness', 'rgb', 'eq_enabled', 'loudness', 'balance']
/** Shown under a control's name. Balance: no left/right wording until verified. */
const NOTE: Partial<Record<LabControl, string>> = {
  loudness: 'הכתיבה אומתה; ההשפעה על הצליל טרם אומתה.',
  balance: 'הטווח, הכיוון וההשפעה טרם אומתו. כל מספר מתקבל.',
}
const OBS: Record<'changed' | 'no_change' | 'unsure', string> = { changed: 'היה שינוי', no_change: 'לא השתנה דבר', unsure: 'לא בטוח' }

const isRgb = (v: unknown): v is Rgb => typeof v === 'object' && v !== null && 'red' in v
const hex = (c: Rgb) => '#' + [c.red, c.green, c.blue].map((n) => n.toString(16).padStart(2, '0')).join('')
const fromHex = (h: string): Rgb => ({ red: parseInt(h.slice(1, 3), 16), green: parseInt(h.slice(3, 5), 16), blue: parseInt(h.slice(5, 7), 16) })
const same = (a: LabValue | null | undefined, b: LabValue | null | undefined) =>
  a != null && b != null && (isRgb(a) && isRgb(b) ? hex(a) === hex(b) : a === b)

function Val({ v }: { v: LabValue | null | undefined }) {
  if (v == null) return <span className="text-muted">—</span>
  if (typeof v === 'boolean') return <span className="font-semibold">{v ? 'מופעל' : 'כבוי'}</span>
  if (isRgb(v)) {
    return (
      <span className="inline-flex items-center gap-1.5 ltr whitespace-nowrap">
        <span className="inline-block w-3.5 h-3.5 rounded-full border border-white/30" style={{ background: hex(v) }} aria-hidden />
        {v.red},{v.green},{v.blue}
      </span>
    )
  }
  return <span className="ltr font-semibold">{v}</span>
}

/** Label above value, in equal columns, so a value never wraps away from its label. */
function Cells({ items }: { items: [string, LabValue | null | undefined][] }) {
  return (
    <dl className="grid gap-2" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted">{k}</dt>
          <dd className="m-0 mt-0.5"><Val v={v} /></dd>
        </div>
      ))}
    </dl>
  )
}

const when = (at: number) => new Date(at * 1000).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' })

/** Admin: try bass and the ambient light's brightness/colour on the real speaker before they become regular controls.
 * Originals are saved first and can be restored. Nothing is written on load; no range is assumed. */
export function SpeakerLab() {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['speaker-lab', token], queryFn: () => api.speakerLab(token), retry: false }) // read only
  const lab = q.data
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const run = async (key: string, fn: () => Promise<Lab>, ok?: (r: Lab) => string | null) => {
    setBusy(key)
    try {
      const r = await fn()
      qc.setQueryData(['speaker-lab', token], r)
      const msg = ok?.(r)
      if (msg) toast('info', msg)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
    } finally { setBusy(null) }
  }

  const snap = lab?.snapshot
  const wrongHost = !!snap && snap.host !== lab?.host
  const missing = snap ? CONTROLS.filter((c) => snap.values[c] === undefined) : []

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <SectionTitle hint="פקדים שהשפעתם טרם אומתה. כל בדיקה מראה מה הרמקול החזיר; רק אתה יכול לקבוע אם היה שינוי בפועל.">
            <span className="inline-flex items-center gap-2"><FlaskConical size={18} aria-hidden /> בדיקת פקדים ניסיוניים ברמקול</span>
          </SectionTitle>
        </div>
        <Key label="קרא שוב מהרמקול" className="!min-w-11 !min-h-11 !rounded-full" onClick={() => void q.refetch()} aria-busy={q.isFetching}>
          <RefreshCw size={18} className={q.isFetching ? 'animate-spin' : ''} aria-hidden />
        </Key>
      </div>

      {q.isPending && <p className="text-sm text-muted" role="status">קורא מהרמקול…</p>}
      {q.isError && <p role="alert" className="text-sm text-danger">{q.error instanceof ApiError ? q.error.message : 'קריאת הרמקול נכשלה.'}</p>}

      {lab && (
        <>
          {/* Step 1: originals */}
          <div className="glass !rounded-2xl p-3 flex flex-col gap-2 text-sm">
            <b>שלב 1: ערכים מקוריים</b>
            {!snap ? (
              <>
                <p className="text-muted">לפני כל בדיקה, קוראים ושומרים בשרת את הערכים הנוכחיים כדי שאפשר יהיה לשחזר אותם.</p>
                <Key label="קרא ושמור ערכים מקוריים" variant="primary" className="h-11 px-4 font-bold self-start"
                  disabled={busy !== null || Object.keys(lab.errors).length > 0}
                  onClick={() => void run('snap', () => api.labSnapshot(token), () => 'הערכים המקוריים נשמרו')}>
                  {busy === 'snap' ? 'קורא…' : 'קרא ושמור ערכים מקוריים'}
                </Key>
              </>
            ) : (
              <>
                <p className="text-xs text-muted">נשמרו ב־{when(snap.at)}</p>
                <Cells items={[['באס', snap.values.bass], ['בהירות', snap.values.brightness], ['צבע', snap.values.rgb]]} />
                <Cells items={[['מתג EQ', snap.values.eq_enabled], ['Loudness', snap.values.loudness], ['איזון', snap.values.balance]]} />
                {missing.length > 0 && !wrongHost && (
                  <div className="flex flex-wrap items-center gap-2 rounded-xl border border-warn/30 bg-warn/5 p-2.5">
                    <p className="text-xs flex-1 min-w-48">השמירה לא כוללת: {missing.map((k) => LABEL[k]).join(', ')}. השלמה קוראת ושומרת רק אותם, בלי לשנות את מה שכבר שמור.</p>
                    <Key label="השלם שמירה" className="h-10 px-3 text-sm font-bold" disabled={busy !== null}
                      onClick={() => void run('snap', () => api.labSnapshot(token), () => 'השמירה הושלמה')}>
                      {busy === 'snap' ? 'קורא…' : 'השלם שמירה'}
                    </Key>
                  </div>
                )}
                {wrongHost && <p role="alert" className="text-danger">הערכים נשמרו מרמקול בכתובת <bdi className="ltr">{snap.host}</bdi>, ולכן הבדיקות והשחזור נעולים.</p>}
                <div className="flex flex-wrap gap-2">
                  <Key label="שחזר ערכים מקוריים" variant="primary" className="h-11 px-4 font-bold" disabled={busy !== null || wrongHost}
                    onClick={() => void run('restore', () => api.labRestore(token), (r) => {
                      const rr = r as Awaited<ReturnType<typeof api.labRestore>>
                      return rr.restored ? 'הערכים המקוריים שוחזרו ואומתו מול הרמקול'
                        : 'השחזור לא הושלם: ' + Object.entries(rr.results).filter(([, x]) => !x.ok).map(([k, x]) => `${LABEL[k as LabControl]}${x.error ? ` (${x.error})` : ''}`).join(', ') + '. הערכים המקוריים נשארו שמורים.'
                    })}>
                    <RotateCcw size={16} aria-hidden /> {busy === 'restore' ? 'משחזר…' : 'שחזר ערכים מקוריים'}
                  </Key>
                  {!confirmDiscard ? (
                    <Key label="בטל את השמירה" className="h-11 px-4" disabled={busy !== null} onClick={() => setConfirmDiscard(true)}>בטל שמירה</Key>
                  ) : (
                    <Key label="אשר ביטול שמירה בלי שחזור" variant="danger" className="h-11 px-4 font-bold" disabled={busy !== null}
                      onClick={() => { setConfirmDiscard(false); void run('discard', () => api.labDiscard(token), () => 'השמירה בוטלה. הרמקול נשאר עם הערכים הנוכחיים.') }}>
                      לבטל בלי לשחזר?
                    </Key>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Step 2: one test per control */}
          {CONTROLS.map((c) => (
            <TestRow key={c} control={c} lab={lab} locked={!snap || wrongHost || busy !== null || snap.values[c] === undefined} busy={busy === c}
              onSend={(v) => void run(c, () => api.labTest(token, c, v))}
              onObserve={(r) => void run('obs-' + c, () => api.labObserve(token, c, r), () => 'התצפית נשמרה')} />
          ))}

          <SourceGainStatus gains={lab.source_gain} error={lab.errors.source_gain} />

          {lab.observations.length > 0 && (
            <div className="text-sm">
              <b>תצפיות שנרשמו</b>
              <ul className="mt-1 flex flex-col divide-y divide-white/5">
                {lab.observations.slice(0, 12).map((o) => (
                  <li key={o.at} className="py-2 flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold flex-1">{LABEL[o.control]}</span>
                      <span className={`chip ${o.result === 'changed' ? 'ok' : o.result === 'no_change' ? 'bad' : ''}`}>{OBS[o.result]}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                      <span className="inline-flex items-center gap-1">נשלח <Val v={o.sent} /></span>
                      <span className="inline-flex items-center gap-1">מדווח <Val v={o.after} /></span>
                      <span className="ms-auto">{when(o.at)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  )
}

function TestRow({ control, lab, locked, busy, onSend, onObserve }: {
  control: LabControl; lab: Lab; locked: boolean; busy: boolean
  onSend: (v: number | Rgb | boolean) => void; onObserve: (r: 'changed' | 'no_change' | 'unsure') => void
}) {
  const current = lab.current[control] ?? null
  // The input starts at the speaker's own value: nothing differs, so nothing can be sent by accident.
  const [text, setText] = useState<string | null>(null)
  const [color, setColor] = useState<string | null>(null)
  const value: LabValue | null = typeof current === 'boolean' ? !current : control === 'rgb'
    ? (color ? fromHex(color) : isRgb(current) ? current : null)
    : text === null ? (typeof current === 'number' ? current : null) : text.trim() === '' ? null : Number(text)
  const valid = value != null && (typeof value === 'boolean' || isRgb(value) || (Number.isFinite(value) && (control !== 'brightness' || Number.isInteger(value))))
  const centred = control === 'balance' && current === 0
  const last: LabProbe | undefined = lab.last[control]
  const answered = last && lab.observations.some((o) => o.control === control && o.at >= last.at)

  return (
    <div className="flex flex-col gap-2 text-sm border-t border-white/5 pt-3">
      <div className="flex items-center gap-2">
        <b className="flex-1"><bdi>{LABEL[control]}</bdi></b>
        <span className="text-muted">עכשיו:</span> <Val v={current} />
      </div>
      {NOTE[control] && <p className="text-xs text-muted -mt-1">{NOTE[control]}</p>}
      {lab.errors[control] && <p className="text-xs text-danger">{lab.errors[control]}</p>}
      <div className="flex items-center gap-2">
        {typeof current === 'boolean' ? (
          <span className="text-muted">הבדיקה תשלח: <b className="text-text">{current ? 'כבה' : 'הפעל'}</b></span>
        ) : control === 'rgb' ? (
          <input type="color" aria-label="צבע לבדיקה" className="h-11 w-20 rounded-xl bg-transparent cursor-pointer disabled:cursor-default"
            value={color ?? (isRgb(current) ? hex(current) : '#000000')} disabled={current == null}
            onChange={(e) => setColor(e.target.value)} />
        ) : (
          <input className="input ltr !w-32" inputMode={control === 'brightness' ? 'numeric' : 'decimal'} aria-label={`${LABEL[control]} לבדיקה`}
            value={text ?? (current == null ? '' : String(current))} disabled={current == null}
            onChange={(e) => setText(e.target.value)} />
        )}
        {control === 'rgb' && value && isRgb(value) && <span className="text-xs text-muted"><Val v={value} /></span>}
        {control === 'balance' && (
          <Key label="מרכז את האיזון (שולח 0)" className="h-11 px-3" disabled={locked || centred} onClick={() => { setText(null); onSend(0) }}>מרכז</Key>
        )}
        <Key label={`שלח בדיקת ${LABEL[control]}`} className="h-11 px-4 font-bold ms-auto"
          disabled={locked || !valid || same(value, current)} onClick={() => valid && onSend(value!)}>
          {busy ? 'שולח…' : 'שלח בדיקה'}
        </Key>
      </div>

      {last && (
        <div className="glass !rounded-xl p-2.5 flex flex-col gap-2">
          <Cells items={[['לפני', last.before], ['נשלח', last.sent], ['הרמקול מדווח', last.after]]} />
          <span className={`chip self-start ${last.speaker_error ? 'bad' : last.stored ? '' : 'demo'}`}>
            {last.speaker_error ? `הרמקול החזיר שגיאה: ${last.speaker_error}` : last.stored ? 'הרמקול שמר את הערך (לא מוכיח שינוי בפועל)' : 'הרמקול שמר ערך אחר מזה שנשלח'}
          </span>
          {!last.speaker_error && (answered ? (
            <p className="text-xs text-muted">התצפית לבדיקה הזו נרשמה.</p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span>מה קרה ברמקול?</span>
              {(['changed', 'no_change', 'unsure'] as const).map((r) => (
                <Key key={r} label={`${LABEL[control]}: ${OBS[r]}`} className="h-9 px-3 !min-h-9 text-xs" onClick={() => onObserve(r)}>{OBS[r]}</Key>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Source gain: read only. The speaker answers "Setting is not modifiable", so there is no control, only the value and
 * the range exactly as reported. No units: they are not verified. */
function SourceGainStatus({ gains, error }: { gains: SourceGain[] | null; error?: string }) {
  return (
    <div className="flex flex-col gap-2 text-sm border-t border-white/5 pt-3">
      <div className="flex items-center gap-2">
        <b className="flex-1"><bdi>Source Gain</bdi></b>
        <span className="chip">לקריאה בלבד</span>
      </div>
      <p className="text-xs text-muted -mt-1">הרמקול מסרב לשנות את הערך הזה, ולכן הוא מוצג בלבד.</p>
      {error && <p className="text-xs text-danger">{error}</p>}
      {gains && gains.length === 0 && <p className="text-xs text-muted">הרמקול לא דיווח ערכים.</p>}
      {gains?.map((g) => (
        <div key={g.name} className="glass !rounded-xl p-2.5">
          <dl className="grid grid-cols-3 gap-2">
            <div><dt className="text-xs text-muted">שם</dt><dd className="m-0 mt-0.5 font-semibold"><bdi>{g.name}</bdi></dd></div>
            <div><dt className="text-xs text-muted">ערך</dt><dd className="m-0 mt-0.5 font-semibold ltr text-start">{g.value}</dd></div>
            <div><dt className="text-xs text-muted">טווח שהרמקול מדווח</dt><dd className="m-0 mt-0.5 font-semibold ltr text-start">{g.min} … {g.max}</dd></div>
          </dl>
        </div>
      ))}
    </div>
  )
}
