import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RotateCcw } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'

/** The restart state the server reports. Read on load; followed closely only while a restart is in progress. */
export function useSpeakerReboot(enabled: boolean) {
  const { token } = useApp()
  return useQuery({
    queryKey: ['speaker-reboot', token], queryFn: () => api.speakerReboot(token), enabled, retry: false,
    refetchInterval: (query) => (query.state.data?.phase === 'restarting' ? 3_000 : false),
  })
}

/** Shown at the top of the speaker card while it restarts (the speaker does not answer meanwhile, so the rest of the
 * card is hidden). "Back" is announced only after the server saw the speaker answer again. */
export function SpeakerRebootStatus({ enabled }: { enabled: boolean }) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const q = useSpeakerReboot(enabled)
  const phase = q.data?.phase
  const seen = useRef(false) // announce the end only if this screen saw the restart in progress
  useEffect(() => {
    if (phase === 'restarting') { seen.current = true; return }
    if (!seen.current || !phase) return
    seen.current = false
    if (phase === 'back') {
      toast('success', `הרמקול חזר לפעול${q.data?.seconds ? ` (אחרי ${q.data.seconds} שניות)` : ''}`)
      void qc.invalidateQueries({ queryKey: ['speaker', token] })
      for (const k of ['speaker-bt', 'speaker-sources', 'speaker-standby', 'speaker-eq', 'speaker-cycle']) void qc.invalidateQueries({ queryKey: [k] })
    } else if (phase === 'timeout') {
      toast('error', 'הרמקול לא חזר לענות אחרי ההפעלה מחדש. בדוק שהוא מחובר לחשמל ולרשת.')
    }
  }, [phase, q.data?.seconds, qc, toast, token])

  if (!enabled || phase !== 'restarting') return null
  return (
    <div role="status" className="flex items-center gap-3 rounded-2xl border border-secondary/30 bg-secondary/[.06] p-3 text-sm">
      <Loader2 size={18} className="text-secondary shrink-0 animate-spin" aria-hidden />
      <p>
        <span className="font-semibold">הרמקול מופעל מחדש…</span>
        <span className="block text-xs text-muted">בדרך כלל לוקח פחות מדקה. המסך יתעדכן כשהרמקול יחזור לענות.</span>
      </p>
    </div>
  )
}

/** The restart button: one fixed action, sent only after a second confirming press. */
export function SpeakerReboot({ enabled }: { enabled: boolean }) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const q = useSpeakerReboot(enabled)
  const restarting = q.data?.phase === 'restarting'

  const go = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await api.speakerRebootStart(token) // resolves only once the speaker stopped answering
      qc.setQueryData(['speaker-reboot', token], r)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'ההפעלה מחדש נכשלה.')
      void q.refetch()
    } finally { setBusy(false); setAsking(false) }
  }

  if (!enabled) return null
  return (
    <div className="flex flex-col gap-2 border-t border-white/5 pt-4">
      <div className="flex items-center gap-3 text-sm">
        <RotateCcw size={16} className="text-muted shrink-0" aria-hidden />
        <span className="flex-1">
          <span className="font-semibold">הפעלה מחדש</span>
          <span className="block text-[11px] text-muted">כמו לחיצה על כפתור ה-RESET הקטן שעל הרמקול</span>
        </span>
        {!asking && (
          <Key label="הפעל מחדש את הרמקול" className="h-10 px-4 text-sm font-bold shrink-0" disabled={busy || restarting}
            onClick={() => setAsking(true)}>
            הפעל מחדש
          </Key>
        )}
      </div>
      {asking && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/[.07] bg-white/[.02] px-3 py-2">
          <p className="flex-1 min-w-40 text-xs text-muted">ההשמעה תיפסק והרמקול ייכבה וידלק מחדש. מכשירי Bluetooth יצטרכו להתחבר שוב.</p>
          <Key variant="danger" label="אשר הפעלה מחדש של הרמקול" className="h-8 px-3 text-xs font-bold" aria-busy={busy}
            disabled={busy} onClick={() => void go()}>
            {busy ? 'מפעיל מחדש…' : 'אשר'}
          </Key>
          <Key label="בטל הפעלה מחדש" className="h-8 px-3 text-xs" disabled={busy} onClick={() => setAsking(false)}>ביטול</Key>
        </div>
      )}
    </div>
  )
}
