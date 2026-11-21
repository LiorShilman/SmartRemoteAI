import type { AuditEntry, CycleConfig, CycleState, EqState, LoadResult, ProfilesState, LabControl, Policy, Rgb, SpeakerBluetooth, SpeakerLab, SpeakerReboot, SpeakerSources, SpeakerStandby, SpeakerState, SpeakerOp, StepCommand, TimeRequest, Usage, Command, CommandOutcome, Device, DeviceKind, ErrorCode, IntentResult, Me, Role, Schedule, TokenCreated, TokenInfo } from '../types'

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

/** Spoken reply as audio (MP3) from the server's Hebrew voice. Only the text is sent; nothing is executed. */
export async function fetchSpeech(token: string, text: string): Promise<Blob> {
  const res = await fetch(API_BASE + '/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ text }),
    signal: AbortSignal.timeout(15000),
  })
  if (!res.ok) throw new Error(`tts ${res.status}`)
  return res.blob()
}

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
  createToken: (token: string, name: string, policy?: Policy) =>
    request<TokenCreated>('/api/tokens', token, { method: 'POST', body: JSON.stringify({ name, ...(policy ? { policy } : {}) }) }),
  setTokenPolicy: (token: string, id: string, policy: Policy | null) =>
    request<TokenInfo>(`/api/tokens/${id}`, token, { method: 'PATCH', body: JSON.stringify({ policy }) }),
  askForTime: (token: string, minutes: 15 | 30 | 60 | 120) =>
    request<TimeRequest>('/api/requests', token, { method: 'POST', body: JSON.stringify({ minutes }) }),
  timeRequests: (token: string) => request<TimeRequest[]>('/api/requests', token),
  decideRequest: (token: string, id: string, approve: boolean, minutes?: number) =>
    request<TimeRequest>(`/api/requests/${id}/decide`, token, { method: 'POST', body: JSON.stringify({ approve, ...(minutes ? { minutes } : {}) }) }),
  usage: (token: string, days = 7) => request<Usage>(`/api/usage?days=${days}`, token),
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
  schedule: (token: string, c: StepCommand, delaySeconds: number, label: string) =>
    request<Schedule>('/api/schedule', token, {
      method: 'POST',
      body: JSON.stringify({ target: c.target, action: c.action, params: c.params ?? {}, delay_seconds: delaySeconds, label }),
    }),
  /** ids: delete exactly those (pending ones are cancelled). No ids: remove everything that is no longer pending. */
  clearSchedules: (token: string, ids?: string[]) =>
    request<{ removed: number }>('/api/schedule/clear', token, { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) }),
  cancelSchedule: (token: string, id: string) => request<Schedule>(`/api/schedule/${id}`, token, { method: 'DELETE' }),
  /** B&W Zeppelin: reading never changes anything on the speaker. */
  speaker: (token: string) => request<SpeakerState>('/api/speaker', token),
  /** Each write resolves only after the server read the value back from the speaker and it matched. */
  speakerVolume: (token: string, value: number) =>
    request<SpeakerState>('/api/speaker/volume', token, { method: 'POST', body: JSON.stringify({ value }) }),
  speakerTreble: (token: string, value: number) =>
    request<SpeakerState>('/api/speaker/treble', token, { method: 'POST', body: JSON.stringify({ value }) }),
  speakerLight: (token: string, enabled: boolean) =>
    request<SpeakerState>('/api/speaker/light', token, { method: 'POST', body: JSON.stringify({ enabled }) }),
  speakerBass: (token: string, value: number) =>
    request<SpeakerState>('/api/speaker/bass', token, { method: 'POST', body: JSON.stringify({ value }) }),
  speakerBrightness: (token: string, value: number) =>
    request<SpeakerState>('/api/speaker/brightness', token, { method: 'POST', body: JSON.stringify({ value }) }),
  speakerLoudness: (token: string, enabled: boolean) =>
    request<SpeakerState>('/api/speaker/loudness', token, { method: 'POST', body: JSON.stringify({ enabled }) }),
  speakerBalance: (token: string, value: number) =>
    request<SpeakerState>('/api/speaker/balance', token, { method: 'POST', body: JSON.stringify({ value }) }),
  /** Automatic colour cycling (runs on the server). Reading it does not contact the speaker. */
  speakerCycle: (token: string) => request<CycleState>('/api/speaker/cycle', token),
  speakerCycleConfig: (token: string, cfg: CycleConfig) =>
    request<CycleState>('/api/speaker/cycle/config', token, { method: 'PUT', body: JSON.stringify(cfg) }),
  speakerCycleStart: (token: string) => request<CycleState>('/api/speaker/cycle/start', token, { method: 'POST' }),
  speakerCycleStop: (token: string) => request<CycleState>('/api/speaker/cycle/stop', token, { method: 'POST' }),
  /** Personal profiles (server-side). Loading is a controlled sequence on the server; a partial load says so. */
  speakerProfiles: (token: string) => request<ProfilesState>('/api/speaker/profiles', token),
  speakerProfileSave: (token: string, name: string, includeVolume: boolean) =>
    request<ProfilesState>('/api/speaker/profiles', token, { method: 'POST', body: JSON.stringify({ name, include_volume: includeVolume }) }),
  speakerProfileRename: (token: string, id: string, name: string) =>
    request<ProfilesState>(`/api/speaker/profiles/${encodeURIComponent(id)}`, token, { method: 'PATCH', body: JSON.stringify({ name }) }),
  /** Overwrite a profile with the speaker's current values (read fresh on the server; nothing is written to the speaker). */
  speakerProfileUpdate: (token: string, id: string) =>
    request<ProfilesState>(`/api/speaker/profiles/${encodeURIComponent(id)}/update`, token, { method: 'POST' }),
  speakerProfileDelete: (token: string, id: string) =>
    request<ProfilesState>(`/api/speaker/profiles/${encodeURIComponent(id)}`, token, { method: 'DELETE' }),
  speakerProfileLoad: (token: string, id: string) =>
    request<LoadResult>(`/api/speaker/profiles/${encodeURIComponent(id)}/load`, token, { method: 'POST' }),
  speakerProfileUndo: (token: string) => request<LoadResult>('/api/speaker/profiles/undo', token, { method: 'POST' }),
  speakerStandby: (token: string) => request<SpeakerStandby>('/api/speaker/standby', token),
  speakerReboot: (token: string) => request<SpeakerReboot>('/api/speaker/reboot', token),
  /** Restarts the speaker; resolves only once it stopped answering. GET speakerReboot reports when it is back. */
  speakerRebootStart: (token: string) => request<SpeakerReboot>('/api/speaker/reboot', token, { method: 'POST' }),
  /** Only an option the speaker lists; resolves with the value read back from the speaker. */
  speakerStandbySet: (token: string, seconds: number) =>
    request<SpeakerStandby>('/api/speaker/standby', token, { method: 'POST', body: JSON.stringify({ seconds }) }),
  speakerSources: (token: string) => request<SpeakerSources>('/api/speaker/sources', token),
  speakerBluetooth: (token: string) => request<SpeakerBluetooth>('/api/speaker/bluetooth', token),
  /** Opens pairing; resolves only once the speaker reports it is visible. Already visible: nothing is sent. */
  speakerPairing: (token: string) => request<SpeakerBluetooth>('/api/speaker/bluetooth/pairing', token, { method: 'POST' }),
  /** One paired device, by its opaque id; resolves only once the speaker no longer lists it as paired. */
  speakerUnpair: (token: string, id: string) =>
    request<SpeakerBluetooth>('/api/speaker/bluetooth/unpair', token, { method: 'POST', body: JSON.stringify({ id }) }),
  /** One voice step (closed list, validated on the server); resolves after the speaker reported the new value. */
  speakerStep: (token: string, op: SpeakerOp, params: Record<string, string | number | boolean>) =>
    request<SpeakerState>('/api/speaker/step', token, { method: 'POST', body: JSON.stringify({ op, params }) }),
  speakerMute: (token: string, enabled: boolean) =>
    request<SpeakerState>('/api/speaker/mute', token, { method: 'POST', body: JSON.stringify({ enabled }) }),
  speakerRgb: (token: string, c: Rgb) =>
    request<SpeakerState>('/api/speaker/rgb', token, { method: 'POST', body: JSON.stringify(c) }),
  /** 5-band equalizer. Reading writes nothing. */
  speakerEq: (token: string) => request<EqState>('/api/speaker/eq', token),
  /** All bands in one request; resolves only after the server read every band back from the speaker and it matched. */
  speakerEqSet: (token: string, bands: { band: string; value: number }[]) =>
    request<EqState>('/api/speaker/eq', token, { method: 'POST', body: JSON.stringify({ bands }) }),
  /** Admin only. Changes the address the server uses; sends nothing to the speaker except a read. */
  speakerConfig: (token: string, host: string) =>
    request<SpeakerState>('/api/speaker/config', token, { method: 'PUT', body: JSON.stringify({ host }) }),
  /** Zeppelin test lab (admin only). Reading writes nothing; tests are refused until the originals are saved. */
  speakerLab: (token: string) => request<SpeakerLab>('/api/speaker/lab', token),
  labSnapshot: (token: string) => request<SpeakerLab>('/api/speaker/lab/snapshot', token, { method: 'POST' }),
  labDiscard: (token: string) => request<SpeakerLab>('/api/speaker/lab/snapshot', token, { method: 'DELETE' }),
  labRestore: (token: string) =>
    request<SpeakerLab & { restored: boolean; results: Record<string, { ok: boolean; now: unknown; error: string | null }> }>('/api/speaker/lab/restore', token, { method: 'POST' }),
  labTest: (token: string, control: LabControl, value: number | Rgb | boolean) =>
    request<SpeakerLab>(`/api/speaker/lab/${control}`, token, { method: 'POST', body: JSON.stringify(control === 'rgb' ? value : { value }) }),
  labObserve: (token: string, control: LabControl, result: 'changed' | 'no_change' | 'unsure') =>
    request<SpeakerLab>('/api/speaker/lab/observation', token, { method: 'POST', body: JSON.stringify({ control, result }) }),
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
