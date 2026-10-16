import type { AuditEntry, Command, CommandOutcome, Device, DeviceKind, ErrorCode, IntentResult, Me, Role, Schedule, TokenCreated, TokenInfo } from '../types'

export const ERROR_TEXT: Record<ErrorCode, string> = {
  NOT_PAIRED: 'המכשיר עדיין לא מצומד. צמד אותו במסך ההגדרות.',
  NOT_CONNECTED: 'השרת לא מחובר למכשיר כרגע.',
  UNSUPPORTED: 'הפעולה לא נתמכת במכשיר הזה.',
  TIMEOUT: 'המכשיר לא הגיב בזמן.',
  DENIED: 'המכשיר דחה את הפעולה.',
  INVALID_COMMAND: 'הפקודה לא תקינה.',
  BACKEND_OFFLINE: 'אין חיבור לשרת השלט. ודא שמחשב ה-Backend פועל באותה רשת.',
  UNAUTHORIZED: 'השרת דחה את האימות. בדוק את קוד הגישה בהגדרות.',
}

/** Empty in dev (Vite proxy). In production the API is a separate HTTPS origin. */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

const DEVICE_IDS: Record<string, string> = { hot: 'hot', lg: 'lg' }

export class ApiError extends Error {
  constructor(public code: ErrorCode, message?: string) {
    super(message ?? ERROR_TEXT[code])
  }
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      signal: AbortSignal.timeout(8000),
    })
  } catch {
    throw new ApiError('BACKEND_OFFLINE')
  }
  if (res.status === 401) throw new ApiError('UNAUTHORIZED')
  if (!res.ok) {
    let code: ErrorCode = 'INVALID_COMMAND'
    let serverMessage: string | undefined
    try {
      const body = await res.json()
      const c = body?.detail?.code ?? body?.code
      if (c && c in ERROR_TEXT) code = c as ErrorCode
      serverMessage = body?.detail?.message // server-written Hebrew explanation, safe to show
    } catch { /* non-JSON body: most likely a proxy error page, i.e. no backend */
      if (res.status >= 502) throw new ApiError('BACKEND_OFFLINE')
    }
    throw new ApiError(code, serverMessage)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  health: (token: string) => request<{ ok: boolean; version: string }>('/api/health', token),
  devices: (token: string) => request<Device[]>('/api/devices', token),
  discover: (token: string) => request<Device[]>('/api/devices/discover', token, { method: 'POST' }),
  addDevice: (token: string, kind: DeviceKind, host: string, role: Role, name?: string) =>
    request<Device>('/api/devices', token, { method: 'POST', body: JSON.stringify({ kind, host, role, ...(name ? { name } : {}) }) }),
  updateDevice: (token: string, id: string, patch: { name?: string; role?: Role; host?: string }) =>
    request<Device>(`/api/devices/${id}`, token, { method: 'PATCH', body: JSON.stringify(patch) }),
  removeDevice: (token: string, id: string) => request<void>(`/api/devices/${id}`, token, { method: 'DELETE' }),
  pointer: (token: string, id: string, ev: { dx?: number; dy?: number; scroll_dy?: number; click?: boolean }) =>
    request<void>(`/api/devices/${id}/pointer`, token, { method: 'POST', body: JSON.stringify(ev) }),
  pairStart: (token: string, id: string) =>
    request<{ status: string }>(`/api/devices/${id}/pair/start`, token, { method: 'POST' }),
  pairConfirm: (token: string, id: string, code: string) =>
    request<Device>(`/api/devices/${id}/pair/confirm`, token, { method: 'POST', body: JSON.stringify({ code }) }),
  me: (token: string) => request<Me>('/api/me', token),
  tokens: (token: string) => request<TokenInfo[]>('/api/tokens', token),
  createToken: (token: string, name: string) => request<TokenCreated>('/api/tokens', token, { method: 'POST', body: JSON.stringify({ name }) }),
  /** Removes REVOKED tokens from the list (ids, or all). Active ones are never removed this way. */
  clearTokens: (token: string, ids?: string[]) =>
    request<{ removed: number }>('/api/tokens/clear', token, { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
  revokeToken: (token: string, id: string) => request<TokenInfo>(`/api/tokens/${id}`, token, { method: 'DELETE' }),
  audit: (token: string, limit = 40) => request<AuditEntry[]>(`/api/audit?limit=${limit}`, token),
  /** A real round trip to the device (not just "sent"). A silent device gets its connection reset. */
  selftest: (token: string, id: string) =>
    request<{ ok: boolean | null; healed: boolean; detail: string }>(`/api/devices/${id}/selftest`, token, { method: 'POST' }),
  setChannel: (token: string, id: string, channel: string) =>
    request<Device>(`/api/devices/${id}/channel`, token, { method: 'POST', body: JSON.stringify({ channel }) }),
  parseIntent: (token: string, text: string, volumeTarget: DeviceKind) =>
    request<IntentResult>('/api/intents/parse', token, { method: 'POST', body: JSON.stringify({ text, volume_target: volumeTarget }) }),
  schedules: (token: string) => request<Schedule[]>('/api/schedule', token),
  schedule: (token: string, c: Command, delaySeconds: number, label: string) =>
    request<Schedule>('/api/schedule', token, {
      method: 'POST',
      body: JSON.stringify({ target: c.target, action: c.action, params: c.params ?? {}, delay_seconds: delaySeconds, label }),
    }),
  /** ids: delete exactly those (pending ones are cancelled). No ids: remove everything that is no longer pending. */
  clearSchedules: (token: string, ids?: string[]) =>
    request<{ removed: number }>('/api/schedule/clear', token, { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
  cancelSchedule: (token: string, id: string) => request<Schedule>(`/api/schedule/${id}`, token, { method: 'DELETE' }),
  async command(token: string, deviceId: string, cmd: Command): Promise<CommandOutcome> {
    try {
      await request(`/api/devices/${deviceId || DEVICE_IDS[cmd.target]}/commands`, token, {
        method: 'POST',
        body: JSON.stringify({
          target: deviceId, action: cmd.action, params: cmd.params ?? {},
          request_id: crypto.randomUUID(),
        }),
      })
      return { ok: true, status: 'sent' }
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'BACKEND_OFFLINE'
      return { ok: false, code, message: e instanceof ApiError ? e.message : ERROR_TEXT[code] }
    }
  },
}
