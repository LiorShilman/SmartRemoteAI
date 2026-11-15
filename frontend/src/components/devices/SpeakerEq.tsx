import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Radio, RefreshCw, RotateCcw, SlidersHorizontal, Undo2 } from 'lucide-react'
import { Card, Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { useBackend } from '../../hooks/useDevices'
import { ApiError, api } from '../../services/api'
import { bandLabel, snapToStep, trebleLabel } from '../../services/speaker'
import type { EqBand, EqState } from '../../types'

const fmt = (v: number) => trebleLabel(v)

// Graph geometry (SVG units). Frequencies run left -> right like every EQ, also in RTL.
const VW = 520, VH = 260
const L = 46, R = 500, T = 34, B = 206 // plot area
const COL = (R - L) / 5

/** Smooth curve through the points (Catmull-Rom as cubic Béziers), extended flat to both edges of the plot. */
function curve(pts: [number, number][]): string {
  if (!pts.length) return ''
  const cy = (y: number) => Math.min(B, Math.max(T, y))
  let d = `M ${L} ${pts[0][1]} L ${pts[0][0]} ${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2
    const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, cy(p1[1] + (p2[1] - p0[1]) / 6)]
    const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, cy(p2[1] - (p3[1] - p1[1]) / 6)]
    d += ` C ${c1[0]} ${c1[1]}, ${c2[0]} ${c2[1]}, ${p2[0]} ${p2[1]}`
  }
  const last = pts[pts.length - 1]
  return d + ` L ${R} ${last[1]}`
}

/** B&W Zeppelin 5-band equalizer, drawn as a graphic EQ. Dragging and the keyboard edit locally only; "החל" sends all
 * bands in one request, so there are never competing writes. Each band's range and step are the speaker's. */
export function SpeakerEq() {
  const { mode, token, toast, eqLive, set } = useApp()
  const backend = useBackend() // always called: hooks must not be conditional
  const live = mode === 'live' && backend === 'online'
  const qc = useQueryClient()
  const applyingRef = useRef(false)
  // Live mode: the newest wanted values, sent after the request in flight is confirmed. Never two requests at once.
  const target = useRef<Record<string, number> | null>(null)
  const editingRef = useRef(false) // a drag or unapplied local edit: a background read must not interfere
  const idle = () => !applyingRef.current && !target.current && !editingRef.current
  const q = useQuery({
    queryKey: ['speaker-eq', token],
    queryFn: () => api.speakerEq(token), // read only
    enabled: live,
    retry: false,
    // pick up changes made on another device, but only while nothing is being edited or sent here
    refetchInterval: () => (idle() ? 10_000 : false),
    refetchOnWindowFocus: () => idle(),
  })
  const bands = q.data?.bands ?? null
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [applying, setApplying] = useState(false)
  const [drag, setDrag] = useState<string | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  if (!live) return null

  const valueOf = (b: EqBand) => draft[b.band] ?? b.value
  const edited = (b: EqBand) => draft[b.band] !== undefined && Math.abs(draft[b.band] - b.value) > 1e-9
  const dirty = !!bands?.some(edited)
  editingRef.current = drag !== null || dirty
  const confirmed = (want: Record<string, number>) => {
    const cur = qc.getQueryData<EqState>(['speaker-eq', token])?.bands
    return !cur || cur.every((b) => Math.abs((want[b.band] ?? b.value) - b.value) < 1e-9)
  }
  /** Live mode: send the newest values, one request at a time, until the speaker reports them. */
  const pushLive = async () => {
    if (applyingRef.current) return // the loop below picks the newest target up
    applyingRef.current = true
    setApplying(true)
    try {
      for (;;) {
        const want = target.current
        const cur = qc.getQueryData<EqState>(['speaker-eq', token])?.bands
        if (!want || !cur || confirmed(want)) break
        const next = await api.speakerEqSet(token, cur.map((b) => ({ band: b.band, value: want[b.band] ?? b.value })))
        qc.setQueryData(['speaker-eq', token], next) // what the speaker reported after the write
      }
      if (target.current && confirmed(target.current)) { target.current = null; setDraft({}) }
    } catch (e) {
      target.current = null
      setDraft({}) // back to what the speaker really has
      toast('error', e instanceof ApiError ? e.message : 'עדכון האקולייזר נכשל.')
      void q.refetch()
    } finally {
      applyingRef.current = false
      setApplying(false)
      if (target.current && !confirmed(target.current)) void pushLive() // a change made while the last reply was arriving
    }
  }
  const change = (next: Record<string, number>) => {
    setDraft(next)
    if (eqLive) { target.current = next; void pushLive() }
  }
  const setLocal = (b: EqBand, v: number) => change({ ...(target.current ?? draft), [b.band]: snapToStep(v, b.min, b.max, b.step) })

  // One dB scale for the whole graph: the widest range any band reports.
  const lo = bands ? Math.min(...bands.map((b) => b.min)) : -6
  const hi = bands ? Math.max(...bands.map((b) => b.max)) : 6
  const y = (v: number) => T + ((hi - v) / (hi - lo || 1)) * (B - T)
  const x = (i: number) => L + COL * (i + 0.5)
  const fromY = (py: number) => hi - ((py - T) / (B - T)) * (hi - lo)
  const ticks = [hi, hi / 2, 0, lo / 2, lo].filter((t, i, a) => t >= lo && t <= hi && a.indexOf(t) === i)

  const pointerValue = (e: PointerEvent, b: EqBand) => {
    const svg = svgRef.current
    const m = svg?.getScreenCTM()
    if (!svg || !m) return
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse())
    setLocal(b, fromY(pt.y))
  }
  const onKey = (e: KeyboardEvent, b: EqBand) => {
    const v = valueOf(b)
    const big = Math.max(b.step, (b.max - b.min) / 8)
    const next = { ArrowUp: v + b.step, ArrowRight: v + b.step, ArrowDown: v - b.step, ArrowLeft: v - b.step,
      PageUp: v + big, PageDown: v - big, Home: b.min, End: b.max }[e.key]
    if (next === undefined) return
    e.preventDefault()
    setLocal(b, next)
  }

  const apply = async () => {
    if (!bands || !dirty || applyingRef.current) return
    applyingRef.current = true
    setApplying(true)
    try {
      const next = await api.speakerEqSet(token, bands.map((b) => ({ band: b.band, value: valueOf(b) })))
      qc.setQueryData(['speaker-eq', token], next) // what the speaker reported after the write
      setDraft({})
      toast('success', 'האקולייזר הוחל: ' + (next.bands ?? []).map((b) => `${bandLabel(b.band)} ${fmt(b.value)}`).join(' · '))
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'החלת האקולייזר נכשלה.')
      void q.refetch() // the edits stay, so they can be applied again
    } finally {
      applyingRef.current = false
      setApplying(false)
    }
  }

  const now = bands?.map((b, i): [number, number] => [x(i), y(valueOf(b))]) ?? []
  const applied = bands?.map((b, i): [number, number] => [x(i), y(b.value)]) ?? []
  const nowPath = curve(now)

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="grid place-items-center w-12 h-12 rounded-2xl bg-white/5 border border-white/10">
          <SlidersHorizontal size={24} className="text-secondary" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-bold text-lg leading-tight">אקולייזר</h3>
          <p className="text-sm text-muted">חמישה תחומים · רמקול Zeppelin</p>
        </div>
        {eqLive ? (
          <span className={`chip ${applying ? '' : 'ok'}`}><Radio size={13} aria-hidden />{applying ? 'שולח…' : 'בזמן אמת'}</span>
        ) : dirty && <span className="chip demo">לא הוחל</span>}
        <Key label="קרא שוב את האקולייזר מהרמקול" className="!min-w-11 !min-h-11 !rounded-full" aria-busy={q.isFetching}
          onClick={() => void q.refetch()}>
          <RefreshCw size={18} className={q.isFetching ? 'animate-spin' : ''} aria-hidden />
        </Key>
      </div>

      {q.isPending && <p className="text-sm text-muted" role="status">קורא מהרמקול…</p>}
      {q.isError && <p role="alert" className="text-sm text-danger">{q.error instanceof ApiError ? q.error.message : 'קריאת האקולייזר נכשלה.'}</p>}
      {q.data?.errors.bands && <p role="alert" className="text-sm text-danger">{q.data.errors.bands}</p>}

      {bands && (
        <>
          <div dir="ltr" className="rounded-2xl border border-white/10 bg-[rgba(8,11,22,.55)] overflow-hidden">
            <svg ref={svgRef} viewBox={`0 0 ${VW} ${VH}`} className="block w-full h-auto select-none touch-none"
              role="group" aria-label="אקולייזר גרפי: גרור נקודה למעלה או למטה, או השתמש בחיצים">
              <defs>
                <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22d3c5" stopOpacity="0.38" />
                  <stop offset="100%" stopColor="#6c6bff" stopOpacity="0.04" />
                </linearGradient>
                <linearGradient id="eq-line" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#6c6bff" />
                  <stop offset="100%" stopColor="#22d3c5" />
                </linearGradient>
                <filter id="eq-glow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="4" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              {/* dB grid */}
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={L} x2={R} y1={y(t)} y2={y(t)} stroke="#a6b3cb" strokeOpacity={t === 0 ? 0.35 : 0.12}
                    strokeDasharray={t === 0 ? undefined : '3 6'} />
                  <text x={L - 10} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#70809f">{fmt(t)}</text>
                </g>
              ))}
              <text x={L - 10} y={T - 16} textAnchor="end" fontSize="10" fill="#70809f">dB</text>

              {/* fader tracks */}
              {bands.map((b, i) => (
                <line key={b.band} x1={x(i)} x2={x(i)} y1={y(b.max)} y2={y(b.min)} stroke="#a6b3cb" strokeOpacity="0.16" strokeWidth="4" strokeLinecap="round" />
              ))}

              {/* response: area, the speaker's current curve (dashed) while there are unapplied edits, and the edited curve */}
              <path d={`${nowPath} L ${R} ${y(0)} L ${L} ${y(0)} Z`} fill="url(#eq-fill)" />
              {dirty && !eqLive && <path d={curve(applied)} fill="none" stroke="#a6b3cb" strokeOpacity="0.45" strokeWidth="1.5" strokeDasharray="4 5" />}
              <path d={nowPath} fill="none" stroke="url(#eq-line)" strokeWidth="3" strokeLinecap="round" filter="url(#eq-glow)" />

              {/* faders: a tall hit area per band, the handle is the accessible slider */}
              {bands.map((b, i) => {
                const v = valueOf(b)
                const active = drag === b.band
                return (
                  <g key={b.band}>
                    <rect x={x(i) - COL / 2} y={T - 20} width={COL} height={B - T + 40} fill="transparent" style={{ cursor: 'ns-resize' }}
                      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setDrag(b.band); pointerValue(e, b) }}
                      onPointerMove={(e) => { if (drag === b.band) pointerValue(e, b) }}
                      onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)} />
                    <text x={x(i)} y={y(v) - 16} textAnchor="middle" fontSize="12.5" fontWeight="700"
                      fill={edited(b) && !eqLive ? '#ffc857' : '#f4f7ff'} opacity={applying ? 0.5 : 1} pointerEvents="none">{fmt(v)}</text>
                    <g role="slider" tabIndex={0} aria-label={bandLabel(b.band)} aria-valuemin={b.min} aria-valuemax={b.max}
                      aria-valuenow={v} aria-valuetext={`${fmt(v)} dB`} data-step={b.step} onKeyDown={(e) => onKey(e, b)}
                      className="eq-handle" style={{ outline: 'none', cursor: 'ns-resize' }}
                      onPointerDown={(e) => { const r = e.currentTarget.parentElement?.querySelector('rect'); r?.setPointerCapture(e.pointerId); setDrag(b.band) }}>
                      <circle cx={x(i)} cy={y(v)} r={active ? 13 : 10} fill="#11182b" stroke={edited(b) && !eqLive ? '#ffc857' : '#22d3c5'} strokeWidth="3"
                        filter="url(#eq-glow)" style={{ transition: 'r 120ms ease' }} />
                      <circle cx={x(i)} cy={y(v)} r="3.5" fill={edited(b) && !eqLive ? '#ffc857' : '#22d3c5'} pointerEvents="none" />
                    </g>
                    <text x={x(i)} y={VH - 22} textAnchor="middle" fontSize="12.5" fontWeight="700" fill="#a6b3cb" pointerEvents="none">{bandLabel(b.band)}</text>
                  </g>
                )
              })}
            </svg>
          </div>

          <p className="text-xs text-muted -mt-1">
            {q.data?.enabled === false && <span className="text-warn">מתג האקולייזר ברמקול כבוי, ולכן השינויים לא יישמעו. </span>}
            {dirty && !eqLive && <><span className="text-warn">צהוב</span> = לא הוחל, קו מקווקו = מה שיש ברמקול עכשיו</>}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            {!eqLive && (
              <Key label="החל את האקולייזר על הרמקול" variant="primary" className="h-11 px-5 font-bold" aria-busy={applying}
                disabled={!dirty && !applying} onClick={() => void apply()}>
                {applying ? 'מחיל…' : 'החל'}
              </Key>
            )}
            <Key label={eqLive ? 'איפוס כל התחומים ל־0' : 'איפוס כל התחומים ל־0 (עד לחיצה על החל)'} className="h-11 px-4"
              onClick={() => change(Object.fromEntries(bands.map((b) => [b.band, snapToStep(0, b.min, b.max, b.step)])))}>
              <RotateCcw size={16} aria-hidden /> איפוס ל־0
            </Key>
            <label className="ms-auto flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" className="w-5 h-5" checked={eqLive}
                onChange={(e) => {
                  set({ eqLive: e.target.checked })
                  if (e.target.checked && dirty) { target.current = draft; void pushLive() } // pending edits go out now
                }} />
              שינויים בזמן אמת
            </label>
            {dirty && !eqLive && (
              <Key label="בטל את השינויים וחזור לערכי הרמקול" className="h-11 px-4" onClick={() => setDraft({})}>
                <Undo2 size={16} aria-hidden /> בטל שינויים
              </Key>
            )}
          </div>
          <p className="text-xs text-muted">
            {eqLive
              ? 'כל שינוי נשלח לרמקול מיד, כל חמשת התחומים יחד ובקשה אחת בכל פעם. מוצגים הערכים שהרמקול מדווח.'
              : 'השינויים נשלחים לרמקול רק בלחיצה על ״החל״, כל חמשת התחומים יחד. אחרי ההחלה מוצגים הערכים שהרמקול מדווח.'}
          </p>
        </>
      )}
    </Card>
  )
}
