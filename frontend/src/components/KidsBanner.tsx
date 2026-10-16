import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Baby, Hourglass } from 'lucide-react'
import { Key } from './ui/Primitives'
import { useApp } from '../app/store'
import { ApiError, api } from '../services/api'
import { useMe } from '../pages/SecurityCards'

const CHOICES: (15 | 30 | 60)[] = [15, 30, 60]

/**
 * Shown to a restricted ("kids mode") access code: what is allowed right now, how much time is left, and a way to
 * ask a parent for more. The limits themselves are enforced by the server; this only explains them.
 */
export function KidsBanner() {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const me = useMe()
  const [asking, setAsking] = useState(false)
  const d = me.data
  if (!d || d.kind !== 'device' || !d.policy) return null

  const closed = d.window_open === false
  const out = d.remaining_min === 0
  const blocked = closed || out
  const msg = closed ? `מחוץ לשעות המותרות (${d.policy.start}–${d.policy.end})`
    : out ? 'מכסת הזמן להיום הסתיימה'
      : `מצב ילדים · פתוח עד ${d.policy.end}${d.remaining_min != null ? ` · נשארו ${d.remaining_min} דק׳` : ''}`

  const ask = async (m: 15 | 30 | 60) => {
    try { await api.askForTime(token, m); toast('success', 'הבקשה נשלחה. מחכים לאישור.'); setAsking(false); void qc.invalidateQueries({ queryKey: ['me'] }) }
    catch (e) { toast('error', e instanceof ApiError ? e.message : 'שליחת הבקשה נכשלה.') }
  }

  return (
    <div role="status" className={`px-4 py-2 text-sm border-b flex flex-wrap items-center gap-x-3 gap-y-2 ${blocked ? 'bg-danger/10 text-danger border-danger/25' : 'bg-secondary/10 text-secondary border-secondary/25'}`}>
      {blocked ? <Hourglass size={16} aria-hidden /> : <Baby size={16} aria-hidden />}
      <span className="flex-1 min-w-40">{msg}{d.extra_min ? ` (+${d.extra_min} דק׳ שאושרו)` : ''}</span>
      {d.request_status === 'pending' ? (
        <span className="chip warn">הבקשה נשלחה, ממתינים לאישור</span>
      ) : asking ? (
        <span className="flex items-center gap-2">
          <span>כמה זמן?</span>
          {CHOICES.map((m) => <Key key={m} label={`בקש ${m} דקות`} className="px-3 h-10 text-sm" onClick={() => void ask(m)}>{m} דק׳</Key>)}
          <Key label="ביטול" className="px-3 h-10 text-sm" onClick={() => setAsking(false)}>ביטול</Key>
        </span>
      ) : (
        <>
          {d.request_status === 'approved' && <span className="chip ok">אושר עוד זמן</span>}
          {d.request_status === 'denied' && <span className="chip">הבקשה נדחתה</span>}
          <Key label="בקש עוד זמן" className="px-3 h-10 text-sm" onClick={() => setAsking(true)}>בקש עוד זמן</Key>
        </>
      )}
    </div>
  )
}
