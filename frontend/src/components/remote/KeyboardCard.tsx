import { useState } from 'react'
import { CornerDownLeft, Delete, Search, Send } from 'lucide-react'
import { Key } from '../ui/Primitives'
import type { Device } from '../../types'
import type { Press } from './Controls'

const APPS = [
  { id: 'youtube', name: 'YouTube' },
  { id: 'netflix', name: 'Netflix' },
  { id: 'spotify', name: 'Spotify' },
] as const

/**
 * Type from the phone into the TV's active text field, and jump straight to an app's search results.
 * What was typed is never put in a label, so it does not end up in the on-screen history.
 */
export function KeyboardCard({ device, press, disabled }: { device: Device; press: Press; disabled?: boolean }) {
  const [text, setText] = useState('')
  const [query, setQuery] = useState('')
  const [app, setApp] = useState<(typeof APPS)[number]['id']>('youtube')
  const isLg = device.kind === 'lg'
  // LG can only search YouTube; Android TV can search all three (Spotify only if it is installed).
  const appOk = (id: string) => !isLg || id === 'youtube'

  const type = (submit: boolean) => {
    if (!text) return
    press({ target: device.kind, action: 'text', params: { text, submit } }, submit ? 'הקלדה + Enter' : 'הקלדה')
    setText('')
  }
  const search = () => {
    if (!query.trim()) return
    const name = APPS.find((a) => a.id === app)!.name
    press({ target: device.kind, action: 'search', params: { app, query: query.trim() } }, `חיפוש ב-${name}`)
  }

  return (
    <div className="flex flex-col gap-5">
      <section aria-label="הקלדה" className="flex flex-col gap-2">
        <h3 className="text-sm font-bold">הקלדה במסך</h3>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); type(false) }}>
          <input className="input flex-1" dir="auto" value={text} maxLength={120} placeholder="הקלד כאן, והטקסט יופיע בשדה הפעיל בטלוויזיה"
            aria-label="טקסט להקלדה בטלוויזיה" onChange={(e) => setText(e.target.value)} disabled={disabled} />
        </form>
        <div className="grid grid-cols-3 gap-2">
          <Key label="שלח טקסט" className="h-11 text-sm" disabled={disabled || !text} onClick={() => type(false)}><Send size={16} /> שלח</Key>
          <Key label="שלח טקסט ו-Enter" variant="primary" className="h-11 text-sm" disabled={disabled || !text} onClick={() => type(true)}><CornerDownLeft size={16} /> שלח + Enter</Key>
          <Key label="מחק תו" className="h-11 text-sm" disabled={disabled}
            onClick={() => press({ target: device.kind, action: 'key_press', params: { key: 'DEL' } }, 'מחיקת תו')}><Delete size={16} /> מחק</Key>
        </div>
        <p className="text-xs text-muted">עובד רק כשיש שדה טקסט פעיל על המסך (למשל חיפוש). אם מוצגת מקלדת על המסך, ייתכן שתצטרך לסגור אותה קודם.</p>
      </section>

      <section aria-label="חיפוש" className="flex flex-col gap-2 pt-4 border-t border-white/5">
        <h3 className="text-sm font-bold">חיפוש ישיר באפליקציה</h3>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="אפליקציה לחיפוש">
          {APPS.map((a) => (
            <Key key={a.id} label={a.name} role="radio" aria-checked={app === a.id} variant={app === a.id ? 'primary' : 'default'}
              className="h-11 text-sm" disabled={disabled || !appOk(a.id)} onClick={() => setApp(a.id)}>{a.name}</Key>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); search() }}>
          <input className="input flex-1" dir="auto" value={query} maxLength={80} placeholder="מה לחפש?" aria-label="מה לחפש"
            onChange={(e) => setQuery(e.target.value)} disabled={disabled} />
          <Key label="חפש" variant="primary" className="px-4 h-12 text-sm" type="submit" disabled={disabled || !query.trim()}><Search size={16} /> חפש</Key>
        </form>
        <p className="text-xs text-muted">
          {isLg ? 'בטלוויזיית LG נתמך חיפוש ב-YouTube בלבד.' : 'נפתחת האפליקציה במסך החיפוש. Netflix: ניסיוני, ו-Spotify דורשת שהאפליקציה מותקנת בממיר.'}
        </p>
      </section>
    </div>
  )
}
