/** Connection driver: 'lg' = LG webOS, 'hot' = Android TV Remote v2 (any Android TV / Google TV box or TV). */
export type DeviceKind = 'hot' | 'lg'
/** What the device is in the room. Independent of the driver. */
export type Role = 'tv' | 'box'
export type Mode = 'demo' | 'live'
export type CapabilityState = 'unknown' | 'supported' | 'unsupported'
export type CapabilityKey =
  | 'nav' | 'volume' | 'mute' | 'channel_step' | 'digits' | 'media'
  | 'power_off' | 'inputs' | 'apps' | 'wol'
export type Connection = 'connected' | 'disconnected' | 'unpaired'

export interface Device {
  id: string
  kind: DeviceKind
  role: Role
  name: string
  host?: string
  connection: Connection
  capabilities: Partial<Record<CapabilityKey, CapabilityState>>
  /** Last adapter error reported by the server (never contains secrets). */
  last_error?: string | null
  /** Channel this server last typed into the box (not read from it; stale after using a physical remote). */
  channel?: string | null
  previous_channel?: string | null
}

export type ErrorCode =
  | 'NOT_PAIRED' | 'NOT_CONNECTED' | 'UNSUPPORTED' | 'TIMEOUT'
  | 'DENIED' | 'INVALID_COMMAND' | 'BACKEND_OFFLINE' | 'UNAUTHORIZED'

export type CommandAction =
  | 'key_press' | 'digits' | 'volume_up' | 'volume_down' | 'mute'
  | 'power_off' | 'power_on' | 'set_input' | 'launch_app' | 'channel_step' | 'channel_last'

export interface Command {
  target: DeviceKind
  /** Exact device to use; without it the first device of that driver is used (voice, schedules). */
  deviceId?: string
  action: CommandAction
  params?: Record<string, string | number | boolean>
}

/** "sent" = the backend accepted and transmitted it. It never means the device visibly reacted. */
export type CommandOutcome =
  | { ok: true; status: 'sent' | 'simulated' }
  | { ok: false; code: ErrorCode; message: string }

export interface IntentStep {
  target: DeviceKind
  action: CommandAction
  params: Record<string, string | number | boolean>
  label: string
  /** >0: run later, scheduled on the server (never a browser timer). */
  delay_seconds: number
}
export interface IntentResult {
  steps: IntentStep[]
  unrecognized: string[]
  /** "rules" (deterministic) or "llm" (optional AI provider configured on the server). */
  provider: 'rules' | 'llm'
}
export interface Schedule {
  id: string
  run_at: number
  target: DeviceKind
  action: CommandAction
  params: Record<string, string | number | boolean>
  label: string
  status: 'pending' | 'done' | 'failed' | 'missed' | 'cancelled'
  error?: string | null
}

export interface Me { kind: 'admin' | 'device'; name: string }
export interface TokenInfo {
  id: string
  name: string
  prefix: string
  created_at: number
  last_used_at: number | null
  last_ip: string | null
  revoked: boolean
}
export interface TokenCreated extends TokenInfo { token: string }
export interface AuditEntry { id: number; at: number; ip: string; who: string; event: string; detail: string }

export interface LogEntry {
  at: number
  mode: Mode
  target: DeviceKind
  deviceId?: string
  label: string
  outcome: 'sent' | 'simulated' | ErrorCode
}
