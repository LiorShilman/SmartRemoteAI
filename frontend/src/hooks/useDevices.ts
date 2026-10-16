import { useQuery } from '@tanstack/react-query'
import { api } from '../services/api'
import { demoDevices } from '../demo/demoEngine'
import { useApp } from '../app/store'
import type { Device, Role } from '../types'

export type BackendStatus = 'demo' | 'checking' | 'online' | 'offline' | 'unauthorized'

export function useBackend(): BackendStatus {
  const { mode, token } = useApp()
  const q = useQuery({
    queryKey: ['health', token],
    queryFn: () => api.health(token),
    enabled: mode === 'live' && token.length > 0, // no code yet: do not knock on the server
    // After a rejection stop polling; changing the token changes the query key and checks again.
    refetchInterval: (query) => ((query.state.error as { code?: string } | null)?.code === 'UNAUTHORIZED' ? false : 8000),
    retry: false,
  })
  if (mode === 'demo') return 'demo'
  if (!token) return 'unauthorized'
  if (q.isPending) return 'checking'
  if (q.isError) return (q.error as { code?: string }).code === 'UNAUTHORIZED' ? 'unauthorized' : 'offline'
  return 'online'
}

/** Devices with user-verified capabilities merged over what the backend reports. */
export function useDevices() {
  const { mode, token, liveCaps, demoCaps } = useApp()
  const backend = useBackend()
  const q = useQuery({
    queryKey: ['devices', token],
    queryFn: () => api.devices(token),
    enabled: mode === 'live' && backend === 'online',
    refetchInterval: 5000,
  })
  const base: Device[] = mode === 'demo' ? demoDevices() : q.data ?? []
  const overrides = mode === 'demo' ? demoCaps : liveCaps
  const devices = base.map((d) => ({ ...d, capabilities: { ...d.capabilities, ...overrides[d.id] } }))
  return { devices, backend, refetch: q.refetch, loading: mode === 'live' && q.isPending && backend === 'online' }
}

/** The device a role's remote shows: the user's selection if it still exists, else the first one. */
export function useRole(role: Role) {
  const { devices, ...rest } = useDevices()
  const selectedId = useApp((s) => s.selected[role])
  const select = useApp((s) => s.select)
  const list = devices.filter((d) => d.role === role)
  const device = list.find((d) => d.id === selectedId) ?? list[0]
  return { devices: list, device, select: (id: string) => select(role, id), ...rest }
}

/** The device that receives volume commands, per the user's preference (falls back to the other role). */
export function useVolumeDevice() {
  const { devices } = useDevices()
  const role = useApp((s) => s.volumeRole)
  const selected = useApp((s) => s.selected)
  const pick = (r: Role) => devices.find((d) => d.id === selected[r] && d.role === r) ?? devices.find((d) => d.role === r)
  return pick(role) ?? pick(role === 'tv' ? 'box' : 'tv')
}
