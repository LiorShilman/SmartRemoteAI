import { useEffect, useRef, useState } from 'react'
import { ChevronsUpDown, MousePointer2, MousePointerClick } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { api } from '../../services/api'
import { useSend } from '../../hooks/useSend'
import type { Device } from '../../types'

const FLUSH_MS = 45 // batch pointer moves so a finger does not become hundreds of requests
const GAIN = 1.9
const SWIPE_STEP_PX = 46 // emulated mode: one arrow press per this much travel
const SWIPE_GAP_MS = 110 // ... and never faster than this

/**
 * Touchpad.
 *  - LG webOS: a real on-screen pointer (move, click, scroll).
 *  - Android TV: the Remote v2 protocol has no pointer, so swipes are translated to arrow keys and a tap to OK.
 *    The UI says so; it is an emulation, not a mouse.
 */
export function Touchpad({ device, disabled }: { device: Device; disabled?: boolean }) {
  const real = device.kind === 'lg'
  const { mode, token, toast } = useApp()
  const { send } = useSend()
  const [hint, setHint] = useState<string | null>(null)
  const acc = useRef({ dx: 0, dy: 0, scroll: 0 })
  const timer = useRef<ReturnType<typeof setInterval>>(undefined)
  const drag = useRef<{ x: number; y: number; t: number; moved: number; stepX: number; stepY: number; lastKey: number } | null>(null)
  const failedOnce = useRef(false)

  const flush = () => {
    const { dx, dy, scroll } = acc.current
    if (!dx && !dy && !scroll) return
    acc.current = { dx: 0, dy: 0, scroll: 0 }
    if (mode !== 'live') return // demo: nothing leaves the browser
    void api.pointer(token, device.id, { dx: Math.round(dx), dy: Math.round(dy), scroll_dy: Math.round(scroll) }).catch((e: Error) => {
      if (!failedOnce.current) { failedOnce.current = true; toast('error', e.message) } // report once, not per event
    })
  }
  useEffect(() => { timer.current = setInterval(flush, FLUSH_MS); return () => clearInterval(timer.current) })

  const click = () => {
    if (mode !== 'live') { toast('demo', 'סימולציה: לחיצה'); return }
    void api.pointer(token, device.id, { click: true }).catch((e: Error) => toast('error', e.message))
  }
  const arrow = (key: string) => void send({ target: device.kind, deviceId: device.id, action: 'key_press', params: { key } }, key, { silent: true })
    .then((o) => { if (!o.ok && !failedOnce.current) { failedOnce.current = true; toast('error', o.message) } })

  const down = (e: React.PointerEvent) => {
    if (disabled) return
    e.currentTarget.setPointerCapture(e.pointerId)
    failedOnce.current = false
    drag.current = { x: e.clientX, y: e.clientY, t: performance.now(), moved: 0, stepX: 0, stepY: 0, lastKey: 0 }
  }
  const move = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    d.x = e.clientX; d.y = e.clientY
    d.moved += Math.abs(dx) + Math.abs(dy)
    if (real) {
      acc.current.dx += dx * GAIN
      acc.current.dy += dy * GAIN
      return
    }
    d.stepX += dx; d.stepY += dy
    const horizontal = Math.abs(d.stepX) >= Math.abs(d.stepY)
    const travel = horizontal ? d.stepX : d.stepY
    if (Math.abs(travel) >= SWIPE_STEP_PX && performance.now() - d.lastKey > SWIPE_GAP_MS) {
      arrow(horizontal ? (travel > 0 ? 'DPAD_RIGHT' : 'DPAD_LEFT') : (travel > 0 ? 'DPAD_DOWN' : 'DPAD_UP'))
      d.stepX = 0; d.stepY = 0; d.lastKey = performance.now()
    }
  }
  const up = () => {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.moved < 8 && performance.now() - d.t < 320) { // a tap
      if (real) click()
      else arrow('DPAD_CENTER')
    }
    flush()
  }

  const scrollDown = (e: React.PointerEvent) => { e.currentTarget.setPointerCapture(e.pointerId); setHint('scroll'); drag.current = { x: e.clientX, y: e.clientY, t: 0, moved: 0, stepX: 0, stepY: 0, lastKey: 0 } }
  const scrollMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || hint !== 'scroll') return
    acc.current.scroll += (e.clientY - d.y) * 0.5
    d.y = e.clientY
  }
  const scrollUp = () => { drag.current = null; setHint(null); flush() }

  return (
    <div className="flex flex-col gap-3" dir="ltr">
      <div className="flex gap-3">
        <div role="application" aria-label={real ? 'משטח עכבר' : 'משטח החלקה'}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
          className={`relative flex-1 h-56 rounded-3xl border border-white/10 bg-gradient-to-br from-white/[.04] to-white/[.01] select-none ${disabled ? 'opacity-40' : 'cursor-grab active:cursor-grabbing'}`}
          style={{ touchAction: 'none' }}>
          <div className="absolute inset-0 grid place-items-center pointer-events-none text-muted text-sm text-center px-6">
            <div className="flex flex-col items-center gap-2">
              <MousePointer2 size={28} aria-hidden className="text-secondary" />
              {real ? 'החלק להזזת המצביע · הקשה = לחיצה' : 'החלק לניווט בחצים · הקשה = OK'}
            </div>
          </div>
        </div>
        {real && (
          <div role="slider" aria-label="גלילה" aria-valuenow={0}
            onPointerDown={scrollDown} onPointerMove={scrollMove} onPointerUp={scrollUp} onPointerCancel={scrollUp}
            className={`w-12 h-56 rounded-3xl border border-white/10 bg-white/[.03] grid place-items-center text-muted ${disabled ? 'opacity-40' : ''}`}
            style={{ touchAction: 'none' }}>
            <ChevronsUpDown size={20} aria-hidden />
          </div>
        )}
      </div>
      {real ? (
        <Key label="לחיצה" className="h-12" disabled={disabled} onClick={click}><MousePointerClick size={18} /> לחיצה</Key>
      ) : (
        <p className="text-xs text-muted text-center" dir="rtl">
          מכשירי Android TV לא תומכים בעכבר אמיתי: המשטח מדמה אותו בלחיצות על חצים. לעכבר אמיתי צריך טלוויזיה מסוג LG webOS.
        </p>
      )}
      {mode === 'demo' && <p className="text-xs text-warn text-center" dir="rtl">מצב הדגמה: לא נשלח דבר למכשיר.</p>}
    </div>
  )
}
