import { useQuery } from '@tanstack/react-query'
import { Radio } from 'lucide-react'
import { useApp } from '../../app/store'
import { api } from '../../services/api'

/** The speaker's own source list ("B&W Audio Sources"), read only: which source is playing and which are connected.
 * Switching is not offered: activating a source node has not been verified on the real speaker. */
export function SpeakerSources({ enabled }: { enabled: boolean }) {
  const { token } = useApp()
  const q = useQuery({ queryKey: ['speaker-sources', token], queryFn: () => api.speakerSources(token), enabled, retry: false, refetchInterval: 15_000 })
  if (!enabled) return null
  if (q.isError) return <p className="text-xs text-danger">לא ניתן לקרוא את מקורות השמע של הרמקול.</p>
  const list = Array.isArray(q.data?.sources) ? q.data.sources : null // guard the shape
  if (!list) return <p className="text-xs text-muted">{q.isPending ? 'קורא מקורות שמע…' : 'רשימת המקורות לא זמינה.'}</p>
  const active = list.find((x) => x.active)
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3 text-sm" role="status">
        <Radio size={18} className={active ? 'text-secondary shrink-0' : 'text-muted shrink-0'} aria-hidden />
        <span className="flex-1">
          {active ? <>מנגן עכשיו מ-<bdi className="font-semibold">{active.title}</bdi></> : 'אין מקור פעיל'}
        </span>
      </div>
      <ul className="flex flex-wrap gap-1.5" aria-label="מקורות שמע">
        {list.map((x) => {
          const state = x.active ? 'פעיל' : x.plugged ? 'מחובר' : 'לא מחובר'
          const look = x.active ? 'border-secondary text-secondary font-bold' : x.plugged ? 'border-white/20' : 'border-white/5 text-muted/60'
          return (
            <li key={x.id} className={`rounded-full px-2.5 py-1 text-[11px] border ${look}`} title={state}>
              <bdi>{x.title}</bdi><span className="sr-only"> ({state})</span>
            </li>
          )
        })}
      </ul>
      <p className="text-[11px] text-muted">מעבר בין מקורות עוד לא נבדק, ולכן כאן רק מוצג המצב.</p>
    </div>
  )
}
