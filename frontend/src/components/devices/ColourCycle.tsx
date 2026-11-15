import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Repeat, Shuffle, X } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'
import { hexToRgb, rgbToHex, type Rgb } from '../../services/speaker'
import type { CycleConfig, CycleState } from '../../types'

const MAX_COLOURS = 12

/** Automatic colour cycling. It runs on the server (it continues with the browser closed); this only shows its state and
 * sends explicit actions: start, stop, and the saved settings. Brightness is never touched. */
export function ColourCycle({ lightOn, disabled, Switch }: {
  lightOn: boolean | null
  disabled: boolean
  Switch: (p: { on: boolean | null; busy: boolean; disabled: boolean; label: string; onToggle: () => void; onText?: string; offText?: string }) => React.ReactNode
}) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['speaker-cycle', token],
    queryFn: () => api.speakerCycle(token), // no speaker request: the server just reports its own state
    refetchInterval: (query) => ((query.state.data as CycleState | undefined)?.status?.running ? 1000 : 15000), // cheap (no speaker request): keeps the shown colour close to the speaker's
    retry: false,
  })
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  // guard the shape: an unexpected reply must not take the card down
  const st = q.data && typeof q.data === 'object' && 'status' in q.data ? q.data.status : undefined
  const cfg = q.data && typeof q.data === 'object' && 'config' in q.data ? q.data.config : undefined

  const run = async (fn: () => Promise<CycleState>, ok?: string) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    try {
      qc.setQueryData(['speaker-cycle', token], await fn())
      if (ok) toast('success', ok)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }
  const save = (patch: Partial<CycleConfig>) => cfg && run(() => api.speakerCycleConfig(token, { ...cfg, ...patch }))

  const running = !!st?.running
  const lightOff = lightOn === false
  return (
    <div className="flex flex-col gap-3 border-t border-white/5 pt-4">
      <div className="flex items-center gap-3">
        <Repeat size={16} className="text-muted shrink-0" aria-hidden />
        <span className="flex-1 text-sm font-semibold">החלפת צבעים אוטומטית</span>
        {Switch({
          on: running, busy, onText: 'פועל', offText: 'כבוי',
          disabled: disabled || busy || !cfg || (!running && lightOff),
          label: running ? 'עצור החלפת צבעים אוטומטית' : 'הפעל החלפת צבעים אוטומטית',
          onToggle: () => void run(running ? () => api.speakerCycleStop(token) : () => api.speakerCycleStart(token),
            running ? 'החלפת הצבעים נעצרה' : 'החלפת הצבעים הופעלה'),
        })}
      </div>

      {!running && lightOff && <p className="text-xs text-warn">יש להדליק את התאורה לפני הפעלת החלפת הצבעים.</p>}
      {st && (st.state === 'disconnected' || st.state === 'error') && <p role="alert" className="text-xs text-danger">{st.message}</p>}
      {st && st.state === 'stopped' && st.message && <p className="text-xs text-muted">{st.message}</p>}
      {q.isError && <p role="alert" className="text-xs text-danger">{q.error instanceof ApiError ? q.error.message : 'לא ניתן לקרוא את מצב החלפת הצבעים.'}</p>}

      {cfg && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="cycle-interval" className="text-muted">מרווח בין צבעים</label>
            <IntervalInput value={cfg.interval_s} disabled={busy} onCommit={(v) => save({ interval_s: v })} />
            <span className="text-muted">שניות</span>
          </div>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="מקור הצבעים">
            {([['palette', 'הפלטה שלי', Repeat], ['random', 'אקראי', Shuffle]] as const).map(([m, label, Icon]) => (
              <Key key={m} label={`צבעים: ${label}`} role="radio" aria-checked={cfg.mode === m} variant={cfg.mode === m ? 'primary' : 'default'}
                className="h-10 text-sm font-bold" disabled={busy} onClick={() => cfg.mode !== m && save({ mode: m })}>
                <Icon size={15} aria-hidden /> {label}
              </Key>
            ))}
          </div>
          <label className="flex items-start gap-2.5 text-sm cursor-pointer">
            <input type="checkbox" className="w-5 h-5 mt-0.5 shrink-0" checked={!!cfg.smooth} disabled={busy}
              onChange={(e) => save({ smooth: e.target.checked })} />
            <span>
              <span className="font-semibold">מעבר הדרגתי</span>
              <span className="block text-xs text-muted">דרך גווני ביניים, עד 3 שניות למעבר.</span>
            </span>
          </label>
          {cfg.mode === 'palette' && (
            <PaletteEditor colours={cfg.palette} disabled={busy} onChange={(palette) => save({ palette })} />
          )}
        </>
      )}
    </div>
  )
}

/** Seconds, saved on Enter or when the field is left; the server keeps it within 3..3600. */
function IntervalInput({ value, disabled, onCommit }: { value: number; disabled: boolean; onCommit: (v: number) => void }) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? String(value)
  const n = Number(shown)
  const valid = Number.isInteger(n) && n >= 3 && n <= 3600
  const commit = () => { if (valid && n !== value) onCommit(n); setText(null) }
  return (
    <>
      <input id="cycle-interval" className="input ltr !w-20 !min-h-10 text-center" inputMode="numeric" value={shown} disabled={disabled}
        aria-invalid={!valid} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit() }} />
      {!valid && <span className="text-xs text-danger w-full">בין 3 ל־3600 שניות.</span>}
    </>
  )
}

/** The user's own colours, in order. Adding uses the picker's "change" (once it closes), not every drag. */
function PaletteEditor({ colours, disabled, onChange }: { colours: Rgb[]; disabled: boolean; onChange: (c: Rgb[]) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const latest = useRef({ colours, onChange })
  latest.current = { colours, onChange }
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const add = () => {
      const c = hexToRgb(el.value)
      const { colours: cur, onChange: change } = latest.current
      if (c && cur.length < MAX_COLOURS) change([...cur, c])
    }
    el.addEventListener('change', add)
    return () => el.removeEventListener('change', add)
  }, [])
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {colours.map((c, i) => (
          <span key={`${rgbToHex(c)}-${i}`} className="relative">
            <span className="block w-8 h-8 rounded-full border-2 border-white/20" style={{ background: rgbToHex(c) }} title={`${c.red},${c.green},${c.blue}`} />
            <button type="button" aria-label={`הסר צבע ${i + 1} מהפלטה`} disabled={disabled}
              onClick={() => onChange(colours.filter((_, k) => k !== i))}
              className="absolute -top-1.5 -end-1.5 grid place-items-center w-5 h-5 rounded-full bg-bg border border-white/30 text-muted hover:text-text disabled:opacity-40">
              <X size={11} aria-hidden />
            </button>
          </span>
        ))}
        {colours.length < MAX_COLOURS && (
          <label className="relative w-8 h-8 rounded-full border-2 border-dashed border-white/30 grid place-items-center cursor-pointer" title="הוסף צבע לפלטה">
            <Plus size={13} aria-hidden />
            <input ref={ref} type="color" aria-label="הוסף צבע לפלטה" defaultValue="#22d3c5" disabled={disabled}
              className="absolute inset-0 opacity-0 cursor-pointer" />
          </label>
        )}
      </div>
      {colours.length < 2 && <p className="text-xs text-warn">צריך לפחות שני צבעים בפלטה.</p>}
    </div>
  )
}
