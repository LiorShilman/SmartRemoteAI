import { Link } from 'react-router-dom'
import { History, Mic, Search } from 'lucide-react'
import { DeviceCard } from '../components/devices/DeviceCard'
import { NetworkMap } from '../components/devices/NetworkMap'
import { Card, SectionTitle } from '../components/ui/Primitives'
import { SelectableRow, SelectToolbar, useSelection } from '../components/ui/Selectable'
import { useDevices } from '../hooks/useDevices'
import { useApp } from '../app/store'
import type { Device, Role } from '../types'

const OUTCOME: Record<string, string> = {
  sent: 'נשלחה', simulated: 'הדמיה',
  NOT_PAIRED: 'לא מצומד', NOT_CONNECTED: 'לא מחובר', UNSUPPORTED: 'לא נתמך', TIMEOUT: 'פג זמן',
  DENIED: 'נדחתה', INVALID_COMMAND: 'לא תקינה', BACKEND_OFFLINE: 'שרת לא זמין', UNAUTHORIZED: 'אימות נכשל',
}

export default function Dashboard() {
  const { devices, loading } = useDevices()
  const { mode, log, removeLog, clearLog, toast } = useApp()
  const shown = log.slice(0, 8)
  const sel = useSelection(shown.map((e) => String(e.at)))
  // One card per device (tv first); a role with no device shows an "add" card so the layout is stable.
  const cards = (['tv', 'box'] as const).flatMap((role): { role: Role; device?: Device }[] => {
    const list = devices.filter((d) => d.role === role)
    return list.length ? list.map((d) => ({ role, device: d })) : [{ role }]
  })

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold">שלום 👋</h1>
        <p className="text-muted">
          {mode === 'demo' ? 'אתה במצב הדגמה — אפשר לבחון את העיצוב ללא מכשירים.' : 'מצב המכשירים בבית, ושליטה בלחיצה.'}
        </p>
      </div>

      <Link to="/voice" className="glass flex items-center gap-3 px-4 min-h-14 no-underline text-text">
        <Search size={20} className="text-muted" aria-hidden />
        <span className="flex-1 text-muted">מה תרצה לראות?</span>
        <span className="grid place-items-center w-10 h-10 rounded-full bg-accent"><Mic size={20} aria-label="מיקרופון" /></span>
      </Link>

      <section aria-labelledby="map-title" className="flex flex-col gap-2">
        <h2 id="map-title" className="text-lg font-bold">מפת חיבורים</h2>
        <NetworkMap devices={devices} />
      </section>

      {loading ? (
        <p className="text-muted" role="status">טוען מכשירים…</p>
      ) : (
        <div className="grid gap-4 grid-cols-[minmax(0,1fr)] md:grid-cols-2">
          {cards.map((c) => <DeviceCard key={c.device?.id ?? c.role} role={c.role} device={c.device} />)}
        </div>
      )}

      <Card>
        <SectionTitle hint="״נשלחה״ אומרת שהפקודה יצאה מהשרת. היא לא מוכיחה שהמכשיר הגיב.">
          <span className="inline-flex items-center gap-2"><History size={18} aria-hidden /> פעולות אחרונות</span>
        </SectionTitle>
        <SelectToolbar s={sel} total={log.length} clearAllLabel="נקה היסטוריה"
          onDeleteSelected={(ids) => { removeLog(ids); toast('info', `נמחקו ${ids.length} פריטים`) }}
          onClearAll={() => { clearLog(); toast('info', 'ההיסטוריה נוקתה') }} />
        {log.length === 0 ? (
          <p className="text-sm text-muted">עדיין לא נשלחו פעולות.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-white/5">
            {shown.map((e) => (
              <SelectableRow key={e.at} s={sel} id={String(e.at)} className="py-2 text-sm">
                <span className="flex-1 min-w-0 break-words">{e.label}</span>
                <span className={`chip ${e.outcome === 'sent' ? 'ok' : e.outcome === 'simulated' ? 'demo' : 'bad'}`}>
                  {OUTCOME[e.outcome] ?? e.outcome}
                </span>
              </SelectableRow>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
