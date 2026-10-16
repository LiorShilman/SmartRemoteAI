import { Link } from 'react-router-dom'
import { Satellite, Tv2, Wifi, WifiOff } from 'lucide-react'
import { Card } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { shortName } from '../../services/deviceName'
import { DRIVER_LABEL, ROLE_LABEL, ROLE_PATH } from '../../services/roles'
import type { Device, Role } from '../../types'

const CONN = {
  connected: ['ok', 'מחובר'],
  disconnected: ['bad', 'מנותק'],
  unpaired: ['', 'לא מצומד'],
} as const

/** One card per device, titled by its role (טלוויזיה / ממיר); the brand/driver is only a subtitle. */
export function DeviceCard({ device, role }: { device?: Device; role: Role }) {
  const mode = useApp((s) => s.mode)
  const select = useApp((s) => s.select)
  const Icon = role === 'tv' ? Tv2 : Satellite
  const conn = device ? CONN[device.connection] : (['', 'לא הוגדר'] as const)
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="grid place-items-center w-12 h-12 rounded-2xl bg-white/5 border border-white/10">
          <Icon size={24} className={role === 'box' ? 'text-accent' : 'text-secondary'} aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-bold text-lg leading-tight">{ROLE_LABEL[role]}</h3>
          <p className="text-sm text-muted break-words">
            {device ? <><bdi>{shortName(device)}</bdi>{shortName(device) === DRIVER_LABEL[device.kind] ? '' : ` · ${DRIVER_LABEL[device.kind]}`}</> : 'אין מכשיר מוגדר'}
          </p>
        </div>
        <span className={`chip ${conn[0]}`}>
          {device?.connection === 'connected' ? <Wifi size={13} aria-hidden /> : <WifiOff size={13} aria-hidden />}
          {conn[1]}
        </span>
      </div>
      {mode === 'demo' && device && <span className="chip demo self-start">הדגמה — לא מכשיר אמיתי</span>}
      <Link
        to={device ? ROLE_PATH[role] : '/settings'}
        onClick={() => device && select(role, device.id)}
        className="key primary px-5 text-base font-bold no-underline text-white self-stretch"
      >
        {device ? 'פתח שלט' : `הוסף ${ROLE_LABEL[role]}`}
      </Link>
    </Card>
  )
}
