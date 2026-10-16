import { useQuery } from '@tanstack/react-query'
import { MonitorPlay } from 'lucide-react'
import { Card, SectionTitle } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { api } from '../../services/api'

function hm(min: number): string {
  if (min < 60) return `${min} דק׳`
  const h = Math.floor(min / 60), m = min % 60
  return m ? `${h}:${String(m).padStart(2, '0')} שע׳` : `${h} שע׳`
}

/** Screen time, measured by the server from what the devices report as their foreground app. Admin only. */
export function UsageCard() {
  const token = useApp((s) => s.token)
  const q = useQuery({ queryKey: ['usage', token], queryFn: () => api.usage(token, 7), refetchInterval: 60_000 })
  if (q.isPending) return null
  if (q.isError || !q.data) return null
  const days = q.data.days
  const max = Math.max(60, ...days.map((d) => d.total_min))
  const today = days[days.length - 1]
  const apps = Object.entries(today.apps).sort((a, b) => b[1] - a[1])
  const empty = days.every((d) => d.total_min === 0)

  return (
    <Card>
      <SectionTitle hint="כמה זמן המסך היה דלוק עם תוכן (טלוויזיה/ממיר), לפי מה שהמכשירים מדווחים. כל מי שצופה נספר, גם ההורים.">
        <span className="inline-flex items-center gap-2"><MonitorPlay size={18} aria-hidden /> זמן מסך</span>
      </SectionTitle>
      {empty ? (
        <p className="text-sm text-muted">עדיין אין נתונים. המדידה מתחילה כשהמכשירים מחוברים ומציגים תוכן.</p>
      ) : (
        <>
          <p className="text-sm mb-3">היום: <b>{hm(today.total_min)}</b></p>
          <div className="flex items-end gap-2 h-28" role="img" aria-label={`זמן מסך לפי יום: ${days.map((d) => `${d.day} ${hm(d.total_min)}`).join(', ')}`}>
            {days.map((d, i) => (
              <div key={d.day} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                <span className="text-[10px] text-muted">{d.total_min ? hm(d.total_min) : ''}</span>
                <div className="w-full rounded-t-lg bg-gradient-to-t from-accent to-secondary" style={{ height: `${Math.max(2, (d.total_min / max) * 80)}px`, opacity: i === days.length - 1 ? 1 : 0.55 }} />
                <span className="text-[10px] text-muted">{new Date(d.day + 'T00:00').toLocaleDateString('he-IL', { weekday: 'short' })}</span>
              </div>
            ))}
          </div>
          {apps.length > 0 && (
            <ul className="flex flex-wrap gap-2 mt-3" aria-label="פילוח היום לפי אפליקציה">
              {apps.map(([a, m]) => <li key={a} className="chip"><bdi>{a}</bdi> · {hm(m)}</li>)}
            </ul>
          )}
        </>
      )}
    </Card>
  )
}
