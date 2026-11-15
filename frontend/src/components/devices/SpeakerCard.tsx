import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AudioLines, Lightbulb, LightbulbOff, Minus, Palette, Plus, RefreshCw, Speaker, Sun, Volume2, VolumeX, Wifi, WifiOff } from 'lucide-react'
import { Card, Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { useBackend } from '../../hooks/useDevices'
import { ApiError, api } from '../../services/api'
import { BASS, BRIGHTNESS, TREBLE, VOLUME, changeToSend, hexToRgb, rgbToHex, snapToStep, trebleLabel, type Rgb } from '../../services/speaker'
import type { CycleState, SpeakerState } from '../../types'
import { ColourCycle } from './ColourCycle'
import { SpeakerBluetooth } from './SpeakerBluetooth'
import { SpeakerSources } from './SpeakerSources'
import { SpeakerStandby } from './SpeakerStandby'

type Num = 'volume' | 'treble' | 'bass' | 'brightness'
type Field = Num | 'light' | 'rgb' | 'mute' | 'loudness'

/** Every numeric control: its range, its +/- step, how it is sent and how a confirmed value is announced. */
const NUM: Record<Num, {
  label: string; range: { min: number; max: number; step: number; button: number }
  send: (token: string, v: number) => Promise<SpeakerState>; show: (v: number) => string
}> = {
  volume: { label: 'עוצמה', range: VOLUME, send: api.speakerVolume, show: String }, // the speaker's own 0..50
  treble: { label: 'גבוהים', range: TREBLE, send: api.speakerTreble, show: trebleLabel },
  bass: { label: 'באס', range: BASS, send: api.speakerBass, show: trebleLabel },
  brightness: { label: 'בהירות', range: BRIGHTNESS, send: api.speakerBrightness, show: String },
}

export function useSpeaker() {
  const { mode, token } = useApp()
  const online = useBackend() === 'online'
  return useQuery({
    queryKey: ['speaker', token],
    queryFn: () => api.speaker(token), // read only
    enabled: mode === 'live' && online,
    refetchInterval: 5_000, // changes made on another phone/computer show up within a few seconds
    retry: false,
  })
}

/** B&W Zeppelin Pro Edition. Shows what the speaker reports; a change is sent only on an explicit user action
 * (releasing a slider, a +/- press, the light button, closing the colour picker), never on load, refresh or polling. */
export function SpeakerCard() {
  const { mode, token, toast } = useApp()
  const backend = useBackend()
  const qc = useQueryClient()
  const q = useSpeaker()
  const s = q.data
  // While cycling, show the colour the server last wrote (polled by the cycle card). Read here, never copied into the
  // speaker data: writing into it every second kept resetting that query's polling timer, so nothing else refreshed.
  const cycle = useQuery<CycleState>({ queryKey: ['speaker-cycle', token], enabled: false }).data
  const cycleColour = cycle?.status?.running ? cycle.status.last_colour : null
  const [draft, setDraft] = useState<Partial<Record<Num, number>>>({})
  const [busy, setBusy] = useState<Partial<Record<Field, boolean>>>({})
  // Controls stay enabled while a change is on its way (disabling them made the cursor flash "not allowed").
  // Quick presses are not lost: the newest wanted value is kept here and sent once the previous one is confirmed.
  const target = useRef<Partial<Record<Num, number>>>({})
  const running = useRef<Partial<Record<Field, boolean>>>({})
  const mark = (f: Field, on: boolean) => { running.current[f] = on; setBusy((b) => ({ ...b, [f]: on })) }
  const fail = (e: unknown) => {
    toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
    void q.refetch() // show what the speaker really has now
  }

  const flush = async (field: Num) => {
    if (running.current[field]) return // the loop below picks the newest target up
    mark(field, true)
    let last = qc.getQueryData<SpeakerState>(['speaker', token])
    let sent = false
    try {
      for (;;) {
        const value = changeToSend(target.current[field], last?.[field])
        if (value === null) break
        last = await NUM[field].send(token, value) // resolves only when the server read the value back from the speaker
        qc.setQueryData(['speaker', token], last)
        sent = true
      }
      const confirmed = last?.[field]
      // announce what the speaker reported after the write, not what was sent
      if (sent && typeof confirmed === 'number') toast('success', `${NUM[field].label}: ${NUM[field].show(confirmed)}`)
    } catch (e) {
      fail(e)
    } finally {
      target.current[field] = undefined
      mark(field, false)
      setDraft((d) => ({ ...d, [field]: undefined }))
    }
  }

  const want = (field: Num, v: number) => {
    const r = NUM[field].range
    const value = snapToStep(v, r.min, r.max, r.step)
    target.current[field] = value
    setDraft((d) => ({ ...d, [field]: value }))
    void flush(field)
  }
  /** +/- steps from the value already on its way, so three quick presses move three steps. */
  const step = (field: Num, delta: number) => {
    const base = target.current[field] ?? s?.[field]
    if (base != null) want(field, base + delta)
  }
  const toggleLight = async () => {
    if (s?.light == null || running.current.light) return
    const enabled = !s.light
    mark('light', true)
    try {
      qc.setQueryData(['speaker', token], await api.speakerLight(token, enabled))
      void qc.invalidateQueries({ queryKey: ['speaker-cycle'] })
      toast('success', enabled ? 'התאורה הודלקה' : 'התאורה כובתה')
    } catch (e) { fail(e) } finally { mark('light', false) }
  }
  /** Loudness: disabled while its request is on its way; a failure shows the error and re-reads the speaker. */
  const toggleLoudness = async () => {
    if (s?.loudness == null || running.current.loudness) return
    const enabled = !s.loudness
    mark('loudness', true)
    try {
      qc.setQueryData(['speaker', token], await api.speakerLoudness(token, enabled)) // server read it back and compared
      toast('success', enabled ? 'Loudness הופעל' : 'Loudness כובה')
    } catch (e) { fail(e) } finally { mark('loudness', false) }
  }
  /** Mute: disabled while its request is on its way; a failure shows the error and re-reads the speaker. */
  const toggleMute = async () => {
    if (s?.mute == null || running.current.mute) return
    const enabled = !s.mute
    mark('mute', true)
    try {
      qc.setQueryData(['speaker', token], await api.speakerMute(token, enabled))
      toast('success', enabled ? 'הרמקול הושתק' : 'ההשתקה בוטלה')
    } catch (e) { fail(e) } finally { mark('mute', false) }
  }
  const setColour = async (c: Rgb) => {
    if (!s?.rgb || running.current.rgb || rgbToHex(c) === rgbToHex(s.rgb)) return
    mark('rgb', true)
    try {
      qc.setQueryData(['speaker', token], await api.speakerRgb(token, c))
      void qc.invalidateQueries({ queryKey: ['speaker-cycle'] })
      toast('success', 'צבע התאורה עודכן')
    } catch (e) { fail(e) } finally { mark('rgb', false) }
  }

  const live = mode === 'live' && backend === 'online'
  const chip: [string, string] = !live ? ['', 'לא זמין'] : q.isPending ? ['', 'בודק…'] : q.isError ? ['bad', 'שגיאה'] : s?.reachable ? ['ok', 'מחובר'] : ['bad', 'מנותק']
  const disabled = (value: unknown) => !live || !s?.reachable || value == null
  const shown = (f: Num) => draft[f] ?? s?.[f] ?? null
  const ctl = (f: Num) => ({
    label: NUM[f].label, value: shown(f), range: NUM[f].range, show: NUM[f].show, busy: !!busy[f],
    error: s?.errors[f], disabled: disabled(s?.[f]),
    onDraft: (v: number) => setDraft((d) => ({ ...d, [f]: v })), onCommit: (v: number) => want(f, v),
    onStep: (dir: 1 | -1) => step(f, dir * NUM[f].range.button),
  })

  return (
    <Card className="flex flex-col gap-5">
      <div className="flex items-start gap-3">
        <div className="grid place-items-center w-12 h-12 rounded-2xl bg-white/5 border border-white/10">
          <Speaker size={24} className="text-secondary" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-bold text-lg leading-tight">רמקול</h3>
          <p className="text-sm text-muted break-words">
            Bowers &amp; Wilkins Zeppelin
            {s?.host && <span className="block text-xs"><bdi className="ltr">{s.host}</bdi></span>}
          </p>
        </div>
        <span className={`chip ${chip[0]}`}>
          {chip[0] === 'ok' ? <Wifi size={13} aria-hidden /> : <WifiOff size={13} aria-hidden />}
          {chip[1]}
        </span>
        <Key label="רענן את מצב הרמקול" className="!min-w-11 !min-h-11 !rounded-full" disabled={!live || q.isFetching}
          onClick={() => void q.refetch()}>
          <RefreshCw size={18} className={q.isFetching ? 'animate-spin' : ''} aria-hidden />
        </Key>
      </div>

      {mode === 'demo' && <p className="text-sm text-muted">השליטה ברמקול זמינה במצב אמיתי בלבד. במצב הדגמה לא נשלח דבר.</p>}
      {mode === 'live' && backend !== 'online' && <p className="text-sm text-muted">אין חיבור לשרת השלט, ולכן אין גישה לרמקול.</p>}
      {live && q.isError && <p role="alert" className="text-sm text-danger">{q.error instanceof ApiError ? q.error.message : 'קריאת מצב הרמקול נכשלה.'}</p>}
      {live && s && !s.reachable && (
        <p role="alert" className="text-sm text-danger">
          הרמקול לא עונה בכתובת <bdi className="ltr">{s.host}</bdi>. ודא שהוא דלוק ומחובר לאותה רשת, או עדכן את הכתובת במסך ההגדרות.
        </p>
      )}

      {live && s?.reachable && (
        <>
          <VolumeDial {...ctl('volume')} />
          <div className="flex items-center justify-center gap-3 -mt-2">
            {s.mute ? <VolumeX size={16} className="text-warn" aria-hidden /> : <Volume2 size={16} className="text-muted" aria-hidden />}
            <span className={`text-sm font-semibold ${s.mute ? 'text-warn' : ''}`}>השתקה</span>
            <Switch on={s.mute} busy={!!busy.mute} disabled={disabled(s.mute) || !!busy.mute} error={s.errors.mute}
              label={s.mute ? 'בטל השתקה' : 'השתק את הרמקול'} onText="מושתק" offText="כבויה"
              iconOn={<VolumeX size={14} className="m-1 text-bg" aria-hidden />} iconOff={<Volume2 size={14} className="m-1 text-bg/60" aria-hidden />}
              onToggle={() => void toggleMute()} />
          </div>

          <Section title="מקור שמע">
            <SpeakerSources enabled={live && !!s.reachable} />
          </Section>

          <Section title="טון">
            <ProSlider {...ctl('bass')} bipolar unit="dB" />
            <ProSlider {...ctl('treble')} bipolar unit="dB" />
            <div className="flex items-center gap-3 border-t border-white/5 pt-4">
              <AudioLines size={16} className="text-muted shrink-0" aria-hidden />
              <span className="flex-1 text-sm font-semibold"><bdi>Loudness</bdi></span>
              <Switch on={s.loudness} busy={!!busy.loudness} disabled={disabled(s.loudness) || !!busy.loudness} error={s.errors.loudness}
                label={s.loudness ? 'כבה Loudness' : 'הפעל Loudness'} onText="פועל" offText="כבוי"
                iconOn={<AudioLines size={14} className="m-1 text-bg" aria-hidden />} iconOff={<AudioLines size={14} className="m-1 text-bg/60" aria-hidden />}
                onToggle={() => void toggleLoudness()} />
            </div>
          </Section>

          <Section title="תאורה" aside={
            <Switch on={s.light} busy={!!busy.light} disabled={disabled(s.light)} error={s.errors.light}
              label={s.light ? 'כבה את תאורת הרמקול' : 'הדלק את תאורת הרמקול'} onToggle={() => void toggleLight()} />
          }>
            <ProSlider {...ctl('brightness')} unit="%" icon={<Sun size={16} aria-hidden />} />
            <ColourField value={cycleColour ?? s.rgb} error={s.errors.rgb} busy={!!busy.rgb} disabled={disabled(s.rgb)} onCommit={(c) => void setColour(c)} />
            <ColourCycle lightOn={s.light} disabled={disabled(s.rgb)} Switch={(p) => <Switch {...p} />} />
          </Section>

          <Section title="Bluetooth">
            <SpeakerBluetooth enabled={live && !!s.reachable} />
          </Section>

          <Section title="חשמל">
            <SpeakerStandby enabled={live && !!s.reachable} />
          </Section>
        </>
      )}
    </Card>
  )
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-white/10 bg-[rgba(8,11,22,.45)] p-4 flex flex-col gap-4">
      <div className="flex items-center gap-3 min-h-8">
        <h4 className="flex-1 text-xs font-bold tracking-widest text-muted">{title}</h4>
        {aside}
      </div>
      {children}
    </section>
  )
}

interface CtlProps {
  label: string; value: number | null; range: { min: number; max: number; step: number; button: number }
  show: (v: number) => string; busy: boolean; error?: string; disabled: boolean
  onDraft: (v: number) => void; onCommit: (v: number) => void; onStep: (dir: 1 | -1) => void
}

function StepKey({ dir, label, disabled, onStep }: { dir: 1 | -1; label: string; disabled: boolean; onStep: (d: 1 | -1) => void }) {
  return (
    <Key label={`${dir > 0 ? 'הגבר' : 'הנמך'} ${label}`} className="!min-w-10 !min-h-10 !rounded-full shrink-0" disabled={disabled} onClick={() => onStep(dir)}>
      {dir > 0 ? <Plus size={16} aria-hidden /> : <Minus size={16} aria-hidden />}
    </Key>
  )
}

/** Volume as a 270° dial. Dragging is RELATIVE (up = louder): a tap never jumps the level. The keyboard and screen
 * readers use the real range input underneath, which is also what the dial shows focus for. */
function VolumeDial(p: CtlProps) {
  const { min, max } = p.range
  const v = p.value ?? min
  const frac = (v - min) / (max - min || 1)
  const C = 110, RAD = 84, START = 135, SWEEP = 270
  const pt = (deg: number, r = RAD): [number, number] => [C + r * Math.cos((deg * Math.PI) / 180), C + r * Math.sin((deg * Math.PI) / 180)]
  const arc = (from: number, to: number) => {
    const [x1, y1] = pt(from), [x2, y2] = pt(to)
    return `M ${x1} ${y1} A ${RAD} ${RAD} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}`
  }
  const end = START + SWEEP * frac
  const [kx, ky] = pt(end)
  const dragRef = useRef<{ y: number; v: number; moved: boolean } | null>(null)
  const [dragging, setDragging] = useState(false)
  const onDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (p.disabled || p.value == null) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { y: e.clientY, v: p.value, moved: false }
    setDragging(true)
  }
  const onMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = dragRef.current
    if (!d) return
    const next = snapToStep(d.v + ((d.y - e.clientY) * (max - min)) / 300, min, max, p.range.step) // 300px = full range
    if (next !== d.v || d.moved) { d.moved = true; p.onDraft(next) }
  }
  const onUp = () => {
    const d = dragRef.current
    dragRef.current = null
    setDragging(false)
    if (d?.moved && p.value != null) p.onCommit(p.value)
  }
  const commit = (e: { currentTarget: HTMLInputElement }) => p.onCommit(Number(e.currentTarget.value))
  // dial only: the arc runs clockwise (minimum bottom-left, maximum bottom-right), so - sits left and + right
  return (
    <div className="flex items-center justify-center gap-4" dir="ltr">
      <StepKey dir={-1} label={p.label} disabled={p.disabled || p.value == null || p.value <= min} onStep={p.onStep} />
      <div className="relative">
        <input type="range" aria-label={p.label} className="peer sr-only" dir="rtl" min={min} max={max} step={p.range.step}
          value={v} aria-valuetext={p.show(v)} disabled={p.disabled} onChange={(e) => p.onDraft(Number(e.currentTarget.value))}
          onKeyUp={commit} onBlur={commit} />
        <svg viewBox="0 0 220 200" className={`w-52 h-auto touch-none select-none rounded-full peer-focus-visible:ring-2 peer-focus-visible:ring-secondary ${p.disabled ? 'opacity-40' : 'cursor-ns-resize'}`}
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} aria-hidden>
          <defs>
            <linearGradient id="vol-arc" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#6c6bff" />
              <stop offset="100%" stopColor="#22d3c5" />
            </linearGradient>
            <filter id="vol-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="5" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {Array.from({ length: 11 }, (_, i) => {
            const deg = START + (SWEEP * i) / 10
            const [x1, y1] = pt(deg, RAD + 12), [x2, y2] = pt(deg, RAD + (i % 5 === 0 ? 20 : 16))
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#a6b3cb" strokeOpacity={i % 5 === 0 ? 0.5 : 0.22} strokeWidth="2" strokeLinecap="round" />
          })}
          <path d={arc(START, START + SWEEP)} fill="none" stroke="#a6b3cb" strokeOpacity="0.14" strokeWidth="12" strokeLinecap="round" />
          {frac > 0.001 && <path d={arc(START, end)} fill="none" stroke="url(#vol-arc)" strokeWidth="12" strokeLinecap="round" filter="url(#vol-glow)" />}
          <circle cx={C} cy={C} r={RAD - 22} fill="#0d1426" stroke="#ffffff" strokeOpacity="0.06" />
          <circle cx={kx} cy={ky} r={dragging ? 11 : 9} fill="#f4f7ff" filter="url(#vol-glow)" style={{ transition: 'r 120ms ease' }} />
          <text x={C} y={C + 12} textAnchor="middle" fontSize="44" fontWeight="800" fill="#f4f7ff" opacity={p.busy ? 0.5 : 1}
            style={{ fontVariantNumeric: 'tabular-nums' }}>{p.value == null ? '—' : p.show(p.value)}</text>
          <text x={C} y={C + 36} textAnchor="middle" fontSize="13" fontWeight="700" fill="#a6b3cb">{p.label}</text>
        </svg>
        {p.error && <p className="text-xs text-danger text-center">{p.error}</p>}
      </div>
      <StepKey dir={1} label={p.label} disabled={p.disabled || p.value == null || p.value >= max} onStep={p.onStep} />
    </div>
  )
}

/** A styled range. `bipolar` fills from the centre (0) to the value, for tone controls. */
function ProSlider(p: CtlProps & { bipolar?: boolean; unit: string; icon?: ReactNode }) {
  const { min, max, step } = p.range
  const v = p.value ?? (p.bipolar ? 0 : min)
  const pct = (x: number) => ((x - min) / (max - min || 1)) * 100
  const a = p.bipolar ? Math.min(pct(0), pct(v)) : 0
  const b = p.bipolar ? Math.max(pct(0), pct(v)) : pct(v)
  const track = `linear-gradient(to left, rgba(166,179,203,.16) 0 ${a}%, #22d3c5 ${a}% ${b}%, rgba(166,179,203,.16) ${b}% 100%)`
  const commit = (e: { currentTarget: HTMLInputElement }) => p.onCommit(Number(e.currentTarget.value))
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-sm">
        {p.icon && <span className="text-muted">{p.icon}</span>}
        <label className="font-semibold flex-1" htmlFor={`pro-${p.label}`}>{p.label}</label>
        {p.error && <span className="text-xs text-danger">{p.error}</span>}
        <span className={`ltr font-bold tabular-nums transition-opacity ${p.busy ? 'opacity-50' : ''}`}>
          {p.value == null ? '—' : p.show(p.value)}<span className="text-xs text-muted font-semibold ms-1">{p.unit}</span>
        </span>
      </div>
      <div className="flex items-center gap-3">
        <StepKey dir={-1} label={p.label} disabled={p.disabled || p.value == null || p.value <= min} onStep={p.onStep} />
        <div className="relative flex-1">
          {p.bipolar && <span aria-hidden className="absolute top-1/2 -translate-y-1/2 w-0.5 h-4 rounded bg-white/40" style={{ right: `calc(${pct(0)}% - 1px)` }} />}
          <input id={`pro-${p.label}`} type="range" dir="rtl" className="pro-range" style={{ ['--track' as string]: track }}
            min={min} max={max} step={step} value={v} disabled={p.disabled}
            onChange={(e) => p.onDraft(Number(e.currentTarget.value))}
            onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
        </div>
        <StepKey dir={1} label={p.label} disabled={p.disabled || p.value == null || p.value >= max} onStep={p.onStep} />
      </div>
    </div>
  )
}

function Switch({ on, busy, disabled, error, label, onToggle, onText = 'דלוקה', offText = 'כבויה', iconOn, iconOff }: {
  on: boolean | null; busy: boolean; disabled: boolean; error?: string; label: string; onToggle: () => void
  onText?: string; offText?: string; iconOn?: ReactNode; iconOff?: ReactNode
}) {
  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-danger">{error}</span>}
      <span className={`text-sm font-semibold ${on ? 'text-secondary' : 'text-muted'}`}>{busy ? 'שולח…' : on == null ? '—' : on ? onText : offText}</span>
      <button type="button" role="switch" aria-checked={on ?? undefined} aria-label={label} aria-busy={busy} disabled={disabled}
        onClick={onToggle} dir="ltr"
        className={`relative w-14 h-8 rounded-full border transition-colors disabled:opacity-40 ${on ? 'bg-secondary/80 border-secondary/60 shadow-[0_0_16px_rgba(34,211,197,.45)]' : 'bg-white/10 border-white/15'}`}>
        <span className={`absolute top-1 w-6 h-6 rounded-full bg-white shadow transition-[left] duration-150 ${on ? 'left-7' : 'left-1'}`}>
          {on ? (iconOn ?? <Lightbulb size={14} className="m-1 text-bg" aria-hidden />) : (iconOff ?? <LightbulbOff size={14} className="m-1 text-bg/60" aria-hidden />)}
        </span>
      </button>
    </div>
  )
}

const SWATCHES: { name: string; c: Rgb }[] = [
  { name: 'לבן חם', c: { red: 255, green: 170, blue: 90 } },
  { name: 'לבן', c: { red: 255, green: 255, blue: 255 } },
  { name: 'ורוד', c: { red: 255, green: 6, blue: 126 } },
  { name: 'סגול', c: { red: 120, green: 80, blue: 255 } },
  { name: 'כחול', c: { red: 24, green: 69, blue: 129 } },
  { name: 'טורקיז', c: { red: 34, green: 211, blue: 197 } },
]

/** Swatches send on click (one explicit action). The custom picker fires "input" while dragging and "change" once it
 * closes: only "change" sends to the speaker. */
function ColourField({ value, error, busy, disabled, onCommit }: {
  value: Rgb | null; error?: string; busy: boolean; disabled: boolean; onCommit: (c: Rgb) => void
}) {
  const ref = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const commit = useRef(onCommit)
  commit.current = onCommit
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onChange = () => { const c = hexToRgb(el.value); if (c) commit.current(c); setDraft(null) }
    el.addEventListener('change', onChange)
    return () => el.removeEventListener('change', onChange)
  }, [])
  const hex = draft ?? (value ? rgbToHex(value) : '#000000')
  const current = value ? rgbToHex(value) : null
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-sm">
        <Palette size={16} className="text-muted" aria-hidden />
        <span className="font-semibold flex-1">צבע</span>
        {error && <span className="text-xs text-danger">{error}</span>}
        {value && (
          <span role="img" aria-label={`הצבע הנוכחי ברמקול: אדום ${value.red}, ירוק ${value.green}, כחול ${value.blue}`}
            title={`${value.red}, ${value.green}, ${value.blue}`}
            className={`flex items-center gap-2 text-xs text-muted transition-opacity ${busy ? 'opacity-50' : ''}`}>
            נוכחי
            <span className="w-6 h-6 rounded-full border border-white/25 transition-[background-color,box-shadow] duration-700" style={{ background: current ?? undefined, boxShadow: `0 0 10px ${current}66` }} />
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        {SWATCHES.map((s) => {
          const h = rgbToHex(s.c)
          const sel = h === current
          return (
            <button key={s.name} type="button" aria-label={`קבע צבע: ${s.name}`} title={s.name} aria-pressed={sel} disabled={disabled}
              onClick={() => onCommit(s.c)}
              className={`w-9 h-9 rounded-full border-2 transition-transform active:scale-95 disabled:opacity-40 ${sel ? 'border-white scale-110' : 'border-white/15'}`}
              style={{ background: h, boxShadow: sel ? `0 0 14px ${h}` : undefined }} />
          )
        })}
        <label className="relative w-9 h-9 rounded-full border-2 border-dashed border-white/30 grid place-items-center cursor-pointer overflow-hidden"
          title="צבע מותאם">
          <Plus size={14} className="text-muted" aria-hidden />
          <input ref={ref} type="color" aria-label="צבע התאורה" value={hex} disabled={disabled}
            className="absolute inset-0 opacity-0 cursor-pointer" onChange={(e) => setDraft(e.target.value)} />
        </label>
      </div>
    </div>
  )
}

