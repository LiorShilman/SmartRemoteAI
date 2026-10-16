import { CirclePlay, Clapperboard, Music } from 'lucide-react'
import { Key } from '../ui/Primitives'
import type { DeviceKind } from '../../types'
import type { Press } from './Controls'

const APPS = [
  { id: 'youtube', name: 'YouTube', Icon: CirclePlay },
  { id: 'netflix', name: 'Netflix', Icon: Clapperboard },
  { id: 'spotify', name: 'Spotify', Icon: Music },
] as const

/** Opens an app on the given device. The server maps the logical name to that device's own app id. */
export function AppLauncher({ target, press, disabled }: { target: DeviceKind; press: Press; disabled?: boolean }) {
  return (
    <div className="grid grid-cols-3 gap-3 ltr">
      {APPS.map(({ id, name, Icon }) => (
        <Key key={id} label={`פתח ${name}`} className="h-16 flex-col !gap-1 text-xs font-semibold" disabled={disabled}
          onClick={() => press({ target, action: 'launch_app', params: { app: id } }, `פתיחת ${name}`)}>
          <Icon size={22} aria-hidden />
          {name}
        </Key>
      ))}
    </div>
  )
}
