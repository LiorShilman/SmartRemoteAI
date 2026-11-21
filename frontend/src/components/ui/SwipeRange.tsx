import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { snapToStep } from '../../services/speaker'

/** A horizontal range for touch screens that never fights the page scroll:
 * - vertical movement is left to the browser (touch-action: pan-y), so scrolling over it scrolls the page;
 * - a value changes only after a clearly sideways drag (8px, more sideways than up/down);
 * - a tap does nothing (no jump to where the finger landed), and the drag is relative to where it started;
 * - the change is committed once, when the finger lifts.
 * Keyboard and screen readers use the real range input underneath. Right-to-left: the minimum is on the right. */
export function SwipeRange({ id, label, min, max, step, value, disabled, bipolar, valueText, onDraft, onCommit }: {
  id?: string; label: string; min: number; max: number; step: number; value: number | null; disabled: boolean
  bipolar?: boolean; valueText: (v: number) => string; onDraft: (v: number) => void; onCommit: (v: number) => void
}) {
  const v = value ?? (bipolar ? 0 : min)
  const pct = (x: number) => ((x - min) / (max - min || 1)) * 100
  const a = bipolar ? Math.min(pct(0), pct(v)) : 0
  const b = bipolar ? Math.max(pct(0), pct(v)) : pct(v)
  const drag = useRef<{ x: number; y: number; v: number; lock: 'x' | 'y' | null; last: number | null } | null>(null)
  const [active, setActive] = useState(false)

  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || value == null) return
    drag.current = { x: e.clientX, y: e.clientY, v: value, lock: null, last: null }
  }
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.lock === 'y') return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (d.lock === null) {
      if (Math.abs(dy) > 8 && Math.abs(dy) >= Math.abs(dx)) { d.lock = 'y'; return } // a scroll: not ours
      if (Math.abs(dx) <= 8) return
      d.lock = 'x'
      e.currentTarget.setPointerCapture(e.pointerId)
      setActive(true)
    }
    const w = e.currentTarget.getBoundingClientRect().width || 1
    const next = snapToStep(d.v - (dx / w) * (max - min), min, max, step) // RTL: leftwards = more
    if (next !== (d.last ?? d.v)) { d.last = next; onDraft(next) }
  }
  const end = (cancelled: boolean) => {
    const d = drag.current
    drag.current = null
    setActive(false)
    if (d?.lock !== 'x' || d.last == null) return
    onCommit(cancelled ? d.v : d.last) // cancelled: back to where it was (nothing is sent when unchanged)
  }
  const commit = (e: { currentTarget: HTMLInputElement }) => onCommit(Number(e.currentTarget.value))

  return (
    <div className="relative flex-1 min-w-0">
      <input id={id} type="range" aria-label={label} className="peer sr-only" dir="rtl" min={min} max={max} step={step} value={v}
        aria-valuetext={valueText(v)} disabled={disabled} onChange={(e) => onDraft(Number(e.currentTarget.value))}
        onKeyUp={commit} onBlur={commit} />
      <div aria-hidden className={`relative h-11 select-none rounded-full peer-focus-visible:ring-2 peer-focus-visible:ring-secondary ${disabled ? 'opacity-40' : ''}`}
        style={{ touchAction: 'pan-y' }}
        onPointerDown={down} onPointerMove={move} onPointerUp={() => end(false)} onPointerCancel={() => end(true)}>
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-[rgba(166,179,203,.16)]">
          <div className="absolute inset-y-0 rounded-full bg-secondary" style={{ right: `${a}%`, width: `${b - a}%` }} />
          {bipolar && <span className="absolute top-1/2 -translate-y-1/2 w-0.5 h-4 rounded bg-white/40" style={{ right: `calc(${pct(0)}% - 1px)` }} />}
        </div>
        <span className={`absolute top-1/2 -translate-y-1/2 translate-x-1/2 rounded-full bg-[#f4f7ff] shadow transition-[width,height] duration-100 ${active ? 'w-6 h-6' : 'w-5 h-5'}`}
          style={{ right: `${pct(v)}%` }} />
      </div>
    </div>
  )
}
