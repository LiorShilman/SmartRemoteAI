import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Delete, Plus, Send, Undo2, X } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import type { Command, DeviceKind } from '../../types'

export type Press = (cmd: Command, label: string) => void

/** Directional pad. Arrow glyphs are physical (left is left) even in RTL. */
export function DPad({ target, press, disabled }: { target: DeviceKind; press: Press; disabled?: boolean }) {
  const k = (key: string, label: string) => () =>
    press({ target, action: 'key_press', params: { key } }, label)
  const arrow = 'absolute w-16 h-16 !rounded-full'
  return (
    <div className="relative mx-auto w-64 h-64 rounded-full glass grid place-items-center ltr" role="group" aria-label="מקשי ניווט">
      <Key label="למעלה" className={`${arrow} top-2 left-1/2 -translate-x-1/2`} disabled={disabled} onClick={k('DPAD_UP', 'למעלה')}>
        <ArrowUp />
      </Key>
      <Key label="למטה" className={`${arrow} bottom-2 left-1/2 -translate-x-1/2`} disabled={disabled} onClick={k('DPAD_DOWN', 'למטה')}>
        <ArrowDown />
      </Key>
      <Key label="שמאלה" className={`${arrow} left-2 top-1/2 -translate-y-1/2`} disabled={disabled} onClick={k('DPAD_LEFT', 'שמאלה')}>
        <ArrowLeft />
      </Key>
      <Key label="ימינה" className={`${arrow} right-2 top-1/2 -translate-y-1/2`} disabled={disabled} onClick={k('DPAD_RIGHT', 'ימינה')}>
        <ArrowRight />
      </Key>
      <Key label="אישור" variant="primary" className="w-24 h-24 !rounded-full text-lg font-extrabold" disabled={disabled}
        onClick={k('DPAD_CENTER', 'אישור')}>
        OK
      </Key>
    </div>
  )
}

/**
 * Numeric keypad.
 *  instant (default): each digit key is sent the moment it is pressed, exactly like a physical remote; the box
 *    itself joins digits typed in quick succession into a channel number. The bottom row has BACK and OK keys.
 *  buffered: build a number locally, then send it as a timed sequence with the send key.
 */
export function Keypad({ target, press, disabled }: { target: DeviceKind; press: Press; disabled?: boolean }) {
  const instant = useApp((s) => s.keypadMode) === 'instant'
  const [buf, setBuf] = useState('')
  const idle = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(idle.current), [])

  const tap = (d: string) => {
    if (instant) {
      press({ target, action: 'key_press', params: { key: `KEYCODE_${d}` } }, `ספרה ${d}`)
      setBuf((b) => (b + d).slice(-4))
      clearTimeout(idle.current)
      idle.current = setTimeout(() => setBuf(''), 3000) // the box starts a new number after a pause, so the display does too
    } else {
      setBuf((b) => (b.length < 4 ? b + d : b))
    }
  }
  const key = (k: string, label: string) => () => press({ target, action: 'key_press', params: { key: k } }, label)
  const digit = 'h-16 text-2xl font-bold'
  return (
    <div className="flex flex-col gap-3">
      <div className="glass !rounded-2xl h-16 grid place-items-center text-4xl font-extrabold tracking-widest ltr" aria-live="polite">
        {buf || <span className="text-muted/40">—</span>}
      </div>
      {instant && <p className="text-xs text-muted text-center -mt-1">כל ספרה נשלחת מיד, כמו בשלט רגיל. הממיר מחבר ספרות רצופות לערוץ.</p>}
      <div className="grid grid-cols-3 gap-3 ltr">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
          <Key key={d} label={`ספרה ${d}`} className={digit} disabled={disabled} onClick={() => tap(d)}>{d}</Key>
        ))}
        {instant ? (
          <Key label="חזור" className="h-16" disabled={disabled} onClick={key('BACK', 'חזור')}><Undo2 /></Key>
        ) : (
          <Key label="מחק ספרה" className="h-16" disabled={disabled || !buf} onClick={() => setBuf((b) => b.slice(0, -1))}><Delete /></Key>
        )}
        <Key label="ספרה 0" className={digit} disabled={disabled} onClick={() => tap('0')}>0</Key>
        {instant ? (
          <Key label="אישור" variant="primary" className="h-16 text-lg font-extrabold" disabled={disabled} onClick={key('DPAD_CENTER', 'אישור')}>OK</Key>
        ) : (
          <Key label="שלח מספר ערוץ" variant="primary" className="h-16" disabled={disabled || !buf}
            onClick={() => { press({ target, action: 'digits', params: { digits: buf } }, `ערוץ ${buf}`); setBuf('') }}>
            <Send />
          </Key>
        )}
      </div>
    </div>
  )
}

/** User-defined favorites only. We never ship a made-up channel list. */
export function Favorites({ target, press, disabled }: { target: DeviceKind; press: Press; disabled?: boolean }) {
  const { favorites, addFavorite, removeFavorite } = useApp()
  const [adding, setAdding] = useState(false)
  const [num, setNum] = useState('')
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(false)

  const save = () => {
    if (!/^\d{1,4}$/.test(num) || !name.trim()) return
    addFavorite({ number: num, name: name.trim() })
    setNum(''); setName(''); setAdding(false)
  }

  return (
    <div>
      {favorites.length === 0 && !adding && (
        <p className="text-sm text-muted mb-3">עדיין אין ערוצים מועדפים. הוסף ערוץ עם המספר והשם שלו.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {favorites.map((f) => (
          <div key={f.id} className="relative">
            <Key label={`ערוץ ${f.number} ${f.name}`} className="px-4 h-14 flex-col !gap-0" disabled={disabled || editing}
              onClick={() => press({ target, action: 'digits', params: { digits: f.number } }, `ערוץ ${f.number} · ${f.name}`)}>
              <span className="text-lg font-extrabold ltr">{f.number}</span>
              <span className="text-xs text-muted">{f.name}</span>
            </Key>
            {editing && (
              <button aria-label={`מחק ${f.name}`} onClick={() => removeFavorite(f.id)}
                className="absolute -top-2 -start-2 w-7 h-7 rounded-full bg-danger text-bg grid place-items-center">
                <X size={16} />
              </button>
            )}
          </div>
        ))}
        <Key label="הוסף ערוץ מועדף" className="px-4 h-14" onClick={() => setAdding((a) => !a)}><Plus /></Key>
      </div>
      {favorites.length > 0 && (
        <button className="text-sm text-muted underline mt-3" onClick={() => setEditing((e) => !e)}>
          {editing ? 'סיום עריכה' : 'עריכת מועדפים'}
        </button>
      )}
      {adding && (
        <form className="flex flex-wrap gap-2 mt-3" onSubmit={(e) => { e.preventDefault(); save() }}>
          <input className="input !w-28 ltr" inputMode="numeric" placeholder="מספר" aria-label="מספר ערוץ"
            value={num} onChange={(e) => setNum(e.target.value.replace(/\D/g, '').slice(0, 4))} />
          <input className="input flex-1 min-w-32" placeholder="שם הערוץ" aria-label="שם הערוץ"
            value={name} onChange={(e) => setName(e.target.value)} />
          <Key label="שמור ערוץ" variant="primary" className="px-5" type="submit">שמור</Key>
        </form>
      )}
    </div>
  )
}
