import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, Mic, MicOff, Play, Send, Sparkles, X } from 'lucide-react'
import { Card, Key, SectionTitle } from '../components/ui/Primitives'
import { SelectableRow, SelectToolbar, useSelection } from '../components/ui/Selectable'
import { useApp } from '../app/store'
import { useSend } from '../hooks/useSend'
import { useBackend, useVolumeDevice } from '../hooks/useDevices'
import { ApiError, api } from '../services/api'
import { needsConfirmation, parseIntent } from '../services/intentParser'
import type { Command, Schedule } from '../types'

interface SpeechRec {
  lang: string; interimResults: boolean; continuous: boolean
  start(): void; stop(): void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}
type SpeechCtor = new () => SpeechRec

const getCtor = (): SpeechCtor | undefined => {
  const w = window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

const MIC_ERRORS: Record<string, string> = {
  'not-allowed': 'ההרשאה למיקרופון נדחתה. אפשר להקליד את הפקודה במקום.',
  'service-not-allowed': 'הדפדפן חסם זיהוי דיבור. אפשר להקליד את הפקודה במקום.',
  'no-speech': 'לא זוהה דיבור. נסה שוב.',
  'audio-capture': 'לא נמצא מיקרופון.',
  network: 'זיהוי הדיבור דורש חיבור לשירות של הדפדפן ולא הצליח להתחבר.',
}

interface PreviewStep { command: Command; label: string; delaySeconds: number }
interface Preview { steps: PreviewStep[]; unrecognized: string[]; provider: 'rules' | 'llm' }

const STATUS: Record<Schedule['status'], [string, string]> = {
  pending: ['', 'ממתין'], done: ['ok', 'בוצע'], failed: ['bad', 'נכשל'], missed: ['bad', 'הוחמץ'], cancelled: ['', 'בוטל'],
}

function when(runAt: number): string {
  const s = Math.round(runAt - Date.now() / 1000)
  if (s <= 0) return 'עכשיו'
  if (s < 90) return `בעוד ${s} שניות`
  if (s < 5400) return `בעוד ${Math.round(s / 60)} דקות`
  return `בעוד ${(s / 3600).toFixed(1)} שעות`
}

export default function VoiceAssistant() {
  const { token, toast } = useApp()
  const volumeTarget = useVolumeDevice()?.kind ?? 'lg' // the driver kind the intent steps are routed by
  const backend = useBackend()
  const live = useApp((s) => s.mode) === 'live'
  const qc = useQueryClient()
  const { send, busy } = useSend()
  const Ctor = getCtor()
  const secure = window.isSecureContext
  const micOk = !!Ctor && secure
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [parsed, setParsed] = useState<Preview | null>(null)
  const [parsing, setParsing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [history, setHistory] = useState<{ id: string; text: string; ran: number }[]>([])
  const recRef = useRef<SpeechRec | null>(null)
  const seq = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => () => { recRef.current?.stop(); clearTimeout(timer.current) }, [])
  useEffect(() => setConfirmed(false), [parsed])

  const schedules = useQuery({
    queryKey: ['schedules', token],
    queryFn: () => api.schedules(token),
    enabled: live && backend === 'online',
    refetchInterval: 5000,
  })

  /** Live: the server parses (rules, or the optional AI provider). Demo: the local deterministic grammar. */
  const preview = (t: string) => {
    setText(t)
    clearTimeout(timer.current)
    const my = ++seq.current
    if (!t.trim()) { setParsed(null); setParsing(false); return }
    if (!live || backend !== 'online') {
      const r = parseIntent(t, { volumeTarget })
      const unrecognized = r.unrecognized.map((u) => (/בעוד/.test(u) && !live ? `${u} (תזמון זמין במצב אמיתי בלבד)` : u))
      setParsed({ steps: r.steps.map((s) => ({ ...s, delaySeconds: 0 })), unrecognized, provider: 'rules' })
      return
    }
    setParsing(true)
    timer.current = setTimeout(async () => {
      try {
        const r = await api.parseIntent(token, t, volumeTarget)
        if (my !== seq.current) return // a newer sentence superseded this one
        setParsed({
          provider: r.provider, unrecognized: r.unrecognized,
          steps: r.steps.map((s) => ({ command: { target: s.target, action: s.action, params: s.params }, label: s.label, delaySeconds: s.delay_seconds })),
        })
      } catch (e) {
        if (my === seq.current) { setParsed(null); toast('error', e instanceof ApiError ? e.message : 'הניתוח נכשל.') }
      } finally {
        if (my === seq.current) setParsing(false)
      }
    }, 350)
  }

  const toggleMic = () => {
    if (!Ctor) return
    if (listening) { recRef.current?.stop(); return }
    const rec = new Ctor()
    rec.lang = 'he-IL'
    rec.interimResults = true
    rec.continuous = false
    rec.onresult = (e) => preview(Array.from(e.results).map((r) => r[0].transcript).join(' '))
    rec.onerror = (e) => toast('error', MIC_ERRORS[e.error] ?? `שגיאת זיהוי קול: ${e.error}`)
    rec.onend = () => setListening(false)
    recRef.current = rec
    setListening(true)
    rec.start() // started only by an explicit press; never always-on
  }

  const run = async () => {
    if (!parsed?.steps.length) return
    let ran = 0
    for (const step of parsed.steps) {
      if (step.delaySeconds > 0) {
        try {
          await api.schedule(token, step.command, step.delaySeconds, step.label)
          toast('success', `תוזמן: ${step.label}`)
          void qc.invalidateQueries({ queryKey: ['schedules'] })
        } catch (e) {
          toast('error', e instanceof ApiError ? e.message : 'התזמון נכשל.')
          break
        }
      } else {
        const o = await send(step.command, step.label)
        if (!o.ok) break // never continue a sequence after a failure
      }
      ran++
    }
    setHistory((h) => [{ id: crypto.randomUUID(), text, ran }, ...h].slice(0, 10))
    setText(''); setParsed(null)
  }

  const cancel = async (id: string) => {
    try { await api.cancelSchedule(token, id) } catch (e) { toast('error', e instanceof ApiError ? e.message : 'הביטול נכשל.') }
    void qc.invalidateQueries({ queryKey: ['schedules'] })
  }

  const risky = parsed?.steps.some((s) => needsConfirmation(s.command))
  const list = schedules.data ?? []
  const schedSel = useSelection(list.map((x) => x.id))
  const histSel = useSelection(history.map((h) => h.id))
  const finished = list.filter((x) => x.status !== 'pending').length

  const clearSchedules = async (ids?: string[]) => {
    try {
      const r = await api.clearSchedules(token, ids)
      toast('info', r.removed ? `נמחקו ${r.removed} פעולות מתוזמנות` : 'אין מה למחוק')
    } catch (e) { toast('error', e instanceof ApiError ? e.message : 'המחיקה נכשלה.') }
    void qc.invalidateQueries({ queryKey: ['schedules'] })
  }

  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-2xl font-extrabold">קול ו-AI</h1>

      <Card className="flex flex-col items-center gap-4">
        <button type="button" onClick={toggleMic} disabled={!micOk}
          aria-label={listening ? 'עצור הקלטה' : 'התחל הקלטה'}
          className={`grid place-items-center w-28 h-28 rounded-full border border-white/20 text-white transition disabled:opacity-40 ${listening ? 'bg-danger shadow-[0_0_50px_rgba(255,102,122,.6)] animate-pulse' : 'bg-accent shadow-[0_0_40px_rgba(108,107,255,.5)]'}`}>
          {micOk ? <Mic size={44} /> : <MicOff size={44} />}
        </button>
        <p className="text-sm text-muted text-center max-w-md" role="status">
          {!Ctor
            ? 'הדפדפן הזה לא תומך בזיהוי דיבור. אפשר להקליד את הפקודה למטה.'
            : !secure
              ? 'מיקרופון דורש חיבור מאובטח (HTTPS) כשנכנסים מהטלפון. בינתיים אפשר להקליד.'
              : listening ? 'מקשיב… דבר עכשיו.' : 'לחץ על המיקרופון ודבר. ההקלטה מתחילה רק בלחיצה.'}
        </p>
        {micOk && (
          <p className="text-xs text-muted text-center max-w-md">
            פרטיות: בחלק מהדפדפנים הדיבור נשלח לשירות הזיהוי של הדפדפן/הספק ואינו מעובד מקומית.
          </p>
        )}
      </Card>

      <Card>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); preview(text) }}>
          <input className="input flex-1" value={text} onChange={(e) => preview(e.target.value)}
            placeholder="למשל: ערוץ 12 ואז תנמיך, או: כבה את הטלוויזיה בעוד שעה" aria-label="פקודה בטקסט" />
        </form>
        <p className="text-xs text-muted mt-2">
          פקודות נתמכות: ערוץ [מספר] · תגביר · תנמיך · השתק · פתח יוטיוב · תעבור ל-HDMI [מספר] · כבה טלוויזיה · בית · חזור.
          {live ? ' אפשר להוסיף ״בעוד שעה / חצי שעה / 20 דקות״ לתזמון בשרת.' : ''}
        </p>

        {parsing && <p className="text-sm text-muted mt-3" role="status">מנתח…</p>}
        {parsed && !parsing && (
          <div className="mt-4 flex flex-col gap-3">
            <SectionTitle hint="זה מה שיבוצע. שום דבר לא נשלח לפני שתאשר.">
              <span className="inline-flex items-center gap-2">
                תצוגה מקדימה
                <span className={`chip ${parsed.provider === 'llm' ? 'ok' : ''}`}>
                  {parsed.provider === 'llm' ? <><Sparkles size={12} aria-hidden /> ניתוח AI</> : 'ניתוח לפי חוקים'}
                </span>
              </span>
            </SectionTitle>
            {parsed.provider === 'llm' && (
              <p className="text-xs text-muted">הטקסט נשלח לספק ה-AI שהוגדר בשרת. הפעולות עוברות אימות רשימה מותרת לפני שיבוצעו.</p>
            )}
            {parsed.steps.length > 0 && (
              <ol className="flex flex-col gap-2">
                {parsed.steps.map((s, i) => (
                  <li key={i} className="glass !rounded-2xl px-4 py-3 text-sm flex items-center gap-3">
                    <span className="grid place-items-center w-6 h-6 rounded-full bg-accent text-xs font-bold shrink-0">{i + 1}</span>
                    <span className="flex-1 min-w-0 break-words">{s.label}</span>
                    {s.delaySeconds > 0 && <span className="chip"><Clock size={12} aria-hidden /> מתוזמן</span>}
                  </li>
                ))}
              </ol>
            )}
            {parsed.unrecognized.length > 0 && (
              <p className="text-sm text-warn" role="alert">
                לא הבנתי: ״{parsed.unrecognized.join('״, ״')}״.{' '}
                {parsed.steps.length > 0 ? 'החלק הזה לא יבוצע.' : 'נסה אחת מהפקודות הנתמכות.'}
              </p>
            )}
            {risky && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="w-5 h-5" />
                אני מאשר פעולה של כיבוי
              </label>
            )}
            <Key label="בצע" variant="primary" className="h-14 font-bold"
              disabled={busy || parsed.steps.length === 0 || (!!risky && !confirmed)} onClick={() => void run()}>
              <Play size={18} /> {parsed.steps.some((s) => s.delaySeconds > 0) ? 'בצע ותזמן' : 'בצע'} {parsed.steps.length > 1 ? `${parsed.steps.length} פעולות` : ''}
            </Key>
          </div>
        )}
      </Card>

      {live && (
        <Card>
          <SectionTitle hint="נשמרות בשרת ושורדות אתחול. פעולה שהוחמצה בזמן שהשרת כבוי לא תרוץ באיחור.">פעולות מתוזמנות</SectionTitle>
          <SelectToolbar s={schedSel} total={list.length} clearAllLabel={`נקה שהסתיימו${finished ? ` (${finished})` : ''}`} deleteLabel="מחק / בטל"
            onDeleteSelected={(ids) => clearSchedules(ids)} onClearAll={() => clearSchedules()} />
          {list.length === 0 ? (
            <p className="text-sm text-muted">אין פעולות מתוזמנות.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-white/5">
              {list.map((s) => (
                <SelectableRow key={s.id} s={schedSel} id={s.id} className="py-2.5 text-sm">
                  <div className="flex-1 min-w-0">
                    <div className="break-words">{s.label || s.action}</div>
                    <div className="text-xs text-muted">
                      {s.status === 'pending' ? when(s.run_at) : new Date(s.run_at * 1000).toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' })}
                      {s.error ? ` · ${s.error}` : ''}
                    </div>
                  </div>
                  <span className={`chip ${STATUS[s.status][0]}`}>{STATUS[s.status][1]}</span>
                  {s.status === 'pending' && !schedSel.on && (
                    <Key label={`בטל ${s.label || s.action}`} className="w-11 h-11" onClick={() => void cancel(s.id)}><X size={18} /></Key>
                  )}
                </SelectableRow>
              ))}
            </ul>
          )}
        </Card>
      )}

      {history.length > 0 && (
        <Card>
          <SectionTitle>בקשות אחרונות</SectionTitle>
          <SelectToolbar s={histSel} total={history.length} clearAllLabel="נקה בקשות"
            onDeleteSelected={(ids) => setHistory((h) => h.filter((x) => !ids.includes(x.id)))} onClearAll={() => setHistory([])} />
          <ul className="flex flex-col divide-y divide-white/5 text-sm">
            {history.map((h) => (
              <SelectableRow key={h.id} s={histSel} id={h.id} className="py-2">
                <Send size={14} className="text-muted shrink-0" /> <span className="flex-1 min-w-0 break-words">{h.text}</span>
                <span className="chip">{h.ran} בוצעו</span>
              </SelectableRow>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
