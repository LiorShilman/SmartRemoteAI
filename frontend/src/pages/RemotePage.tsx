import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Satellite, Tv2 } from 'lucide-react'
import { Card, Key } from '../components/ui/Primitives'
import { useApp } from '../app/store'
import { ApiError, api } from '../services/api'
import { useRole } from '../hooks/useDevices'
import { DRIVER_LABEL, ROLE_LABEL } from '../services/roles'
import { shortName } from '../services/deviceName'
import type { Role } from '../types'
import WebOsPanel from './panels/WebOsPanel'
import AndroidPanel from './panels/AndroidPanel'

/** One remote page per role (tv / box). The controls shown depend on the selected device's connection type. */
export default function RemotePage({ role }: { role: Role }) {
  const { devices, device, select, loading } = useRole(role)
  const Icon = role === 'tv' ? Tv2 : Satellite
  const { mode, token } = useApp()
  const [test, setTest] = useState<{ tone: 'ok' | 'bad' | ''; text: string } | null>(null)
  const [testing, setTesting] = useState(false)

  const runTest = async () => {
    if (!device) return
    setTesting(true); setTest(null)
    try {
      const r = await api.selftest(token, device.id)
      setTest({ tone: r.ok ? 'ok' : r.ok === false ? 'bad' : '', text: r.detail })
    } catch (e) {
      setTest({ tone: 'bad', text: e instanceof ApiError ? e.message : 'הבדיקה נכשלה.' })
    } finally { setTesting(false) }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <Icon aria-hidden className="text-secondary" />
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold leading-tight">שלט {ROLE_LABEL[role]}</h1>
          {device && <p className="text-sm text-muted truncate"><bdi>{shortName(device)}</bdi>{shortName(device) === DRIVER_LABEL[device.kind] ? '' : ` · ${DRIVER_LABEL[device.kind]}`}</p>}
        </div>
      </div>

      {device && mode === 'live' && (
        <div className="flex flex-wrap items-center gap-3">
          <Key label="בדיקת חיבור" className="px-4 h-11 text-sm" disabled={testing || device.connection !== 'connected'} onClick={() => void runTest()}>
            <Activity size={16} aria-hidden /> {testing ? 'בודק…' : 'בדיקת חיבור'}
          </Key>
          {test && <span role="status" className={`chip ${test.tone}`}>{test.text}</span>}
        </div>
      )}

      {devices.length > 1 && (
        <div role="radiogroup" aria-label={`בחירת ${ROLE_LABEL[role]}`} className="flex flex-wrap gap-2">
          {devices.map((d) => (
            <button key={d.id} type="button" role="radio" aria-checked={d.id === device?.id} onClick={() => select(d.id)}
              className={`chip !text-sm !px-4 !py-2 ${d.id === device?.id ? 'ok' : ''}`}>
              <span className={`w-2 h-2 rounded-full ${d.connection === 'connected' ? 'bg-[#34d399]' : d.connection === 'disconnected' ? 'bg-danger' : 'bg-muted'}`} />
              <bdi>{shortName(d)}</bdi>
            </button>
          ))}
        </div>
      )}

      {!device ? (
        <Card className="text-center flex flex-col gap-3 items-center">
          <p>{loading ? 'טוען מכשירים…' : `אין ${ROLE_LABEL[role]} מוגדרת.`}</p>
          {!loading && <Link to="/settings" className="key primary px-6 no-underline text-white">הוסף מכשיר</Link>}
        </Card>
      ) : device.kind === 'lg' ? (
        <WebOsPanel key={device.id} device={device} />
      ) : (
        <AndroidPanel key={device.id} device={device} />
      )}
    </div>
  )
}
