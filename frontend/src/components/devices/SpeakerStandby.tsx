import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Power } from 'lucide-react'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'

/** Hebrew name for a standby value in seconds. */
export const standbyLabel = (sec: number) => (sec === 0 ? 'כבוי' : sec % 60 === 0 ? `${sec / 60} דקות` : `${sec} שניות`)

/** Standby timeout: a choice from the list the speaker itself publishes. Reading only on load; a write is sent only
 * when the user picks a different option, and the value shown afterwards is the one the speaker reported. */
export function SpeakerStandby({ enabled }: { enabled: boolean }) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const q = useQuery({ queryKey: ['speaker-standby', token], queryFn: () => api.speakerStandby(token), enabled, retry: false })
  const d = q.data && typeof q.data.seconds === 'number' && Array.isArray(q.data.options) ? q.data : undefined
  const pick = async (sec: number) => {
    if (busy || !d || sec === d.seconds) return
    setBusy(true)
    try {
      const r = await api.speakerStandbySet(token, sec) // resolves only after the server read the value back
      qc.setQueryData(['speaker-standby', token], r)
      toast('success', `כיבוי אוטומטי: ${standbyLabel(r.seconds)}`)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally { setBusy(false) }
  }

  if (!enabled) return null
  if (q.isError) return <p className="text-xs text-danger">לא ניתן לקרוא את זמן הכיבוי של הרמקול.</p>
  if (!d) return <p className="text-xs text-muted">{q.isPending ? 'קורא זמן כיבוי…' : 'זמן הכיבוי לא זמין.'}</p>
  const listed = d.options.some((o) => o.seconds === d.seconds)
  return (
    <div className="flex items-center gap-3 text-sm">
      <Power size={16} className="text-muted shrink-0" aria-hidden />
      <span className="flex-1">
        <span className="font-semibold">כיבוי אוטומטי</span>
        <span className="block text-[11px] text-muted">אחרי זמן ללא השמעה</span>
      </span>
      {/* the shared dark drop-down style (dark options list, own arrow); sized down to fit the row */}
      <select className="input !w-auto !min-h-10 h-10 !rounded-xl text-sm disabled:opacity-50" aria-busy={busy}
        aria-label="כיבוי אוטומטי אחרי זמן ללא השמעה" value={d.seconds} disabled={busy}
        onChange={(e) => void pick(Number(e.currentTarget.value))}>
        {!listed && <option value={d.seconds} disabled>{standbyLabel(d.seconds)} (מוגדר כעת)</option>}
        {d.options.map((o) => <option key={o.seconds} value={o.seconds}>{standbyLabel(o.seconds)}</option>)}
      </select>
    </div>
  )
}
