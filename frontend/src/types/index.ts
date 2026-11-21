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
  | 'power_off' | 'power_on' | 'set_input' | 'launch_app' | 'channel_step' | 'channel_last' | 'text' | 'search'

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

/** Voice / schedule steps for the speaker: a closed list the server validates (no paths, no raw values). */
export type SpeakerOp =
  | 'speaker_volume' | 'speaker_mute' | 'speaker_bass' | 'speaker_treble' | 'speaker_light'
  | 'speaker_brightness' | 'speaker_color' | 'speaker_cycle' | 'speaker_profile'
export interface SpeakerCommand {
  target: 'speaker'
  action: SpeakerOp
  params?: Record<string, string | number | boolean>
}
/** What a voice step or a schedule can run: a device command, or a speaker step. */
export type StepCommand = Command | SpeakerCommand

export interface IntentStep {
  target: DeviceKind | 'speaker'
  action: CommandAction | SpeakerOp
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
  target: DeviceKind | 'speaker'
  action: CommandAction | SpeakerOp
  params: Record<string, string | number | boolean>
  label: string
  status: 'pending' | 'done' | 'failed' | 'missed' | 'cancelled'
  error?: string | null
}

/** Kids mode: what a restricted access code may do (enforced by the server). */
export interface Policy {
  start: string
  end: string
  apps: ('youtube' | 'netflix' | 'spotify')[]
  can_power_off: boolean
  can_schedule: boolean
  daily_limit_min: number | null
}
export interface Me {
  kind: 'admin' | 'device'
  name: string
  policy?: Policy | null
  used_min?: number | null
  remaining_min?: number | null
  extra_min?: number
  window_open?: boolean | null
  request_status?: 'pending' | 'approved' | 'denied' | null
  pending_requests?: number | null
}
export interface TimeRequest {
  id: string
  token_id: string
  token_name: string
  minutes: number
  status: 'pending' | 'approved' | 'denied'
  created_at: number
  decided_at: number | null
  granted_minutes: number
}
export interface UsageDay { day: string; total_min: number; apps: Record<string, number> }
export interface Usage { today_min: number; days: UsageDay[] }
export interface TokenInfo {
  id: string
  name: string
  prefix: string
  created_at: number
  last_used_at: number | null
  last_ip: string | null
  revoked: boolean
  policy?: Policy | null
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

/** B&W Zeppelin speaker, as read by the server. null = that value could not be read (see errors). */
/** Speaker Bluetooth (read from bluetooth:state). `sent` only on a pairing request: false = already visible. */
export interface SpeakerReboot { phase: 'idle' | 'restarting' | 'back' | 'timeout'; seconds: number | null }
export interface SpeakerStandby { seconds: number; options: { seconds: number; title: string }[] }
export interface SpeakerSource { id: string; title: string; active: boolean; plugged: boolean; available: boolean }
export interface SpeakerSources { sources: SpeakerSource[] }

export interface SpeakerBluetooth {
  name: string
  discoverable: boolean
  pairable: boolean
  connected_device: string | null
  paired: string[]
  /** Paired devices as the speaker's own menu lists them (null/absent = unreadable). Ids are opaque, never addresses. */
  devices?: SpeakerBtDevice[] | null
  /** How long the speaker keeps pairing open, its own setting (read only). */
  pairing_seconds?: number | null
  sent?: boolean | null
  unpaired?: string | null
}
export interface SpeakerBtDevice { id: string; name: string; roles: ('input' | 'speaker')[] }

export interface SpeakerState {
  host: string
  reachable: boolean
  volume: number | null
  treble: number | null
  light: boolean | null
  bass: number | null
  brightness: number | null
  rgb: { red: number; green: number; blue: number } | null
  mute: boolean | null
  loudness: boolean | null
  /** Range and which sign is left/right are unknown. */
  balance: number | null
  /** Read only, as the speaker reports it: "online", "networkStandby", ... (optional: older servers omit it). */
  power?: string | null
  power_reason?: string | null
  errors: Record<string, string>
}

/** Zeppelin test lab (admin): controls whose write effect is not verified yet. */
export type LabControl = 'bass' | 'brightness' | 'rgb' | 'eq_enabled' | 'loudness' | 'balance'
export interface Rgb { red: number; green: number; blue: number }
export type LabValue = number | Rgb | boolean
export interface LabValues {
  bass: number | null; brightness: number | null; rgb: Rgb | null
  /** Optional: a snapshot saved before these were in the lab lacks them until it is completed. */
  eq_enabled?: boolean | null; loudness?: boolean | null; balance?: number | null
}
/** Source gain as the speaker reports it. Read only: the speaker refuses to change it. Units not verified. */
export interface SourceGain { name: string; value: number; min: number; max: number }
/** One test: what was sent and what the speaker reported. `stored` is NOT "it worked" — only the user can tell that. */
export interface LabProbe {
  control: LabControl; sent: LabValue; before: LabValue; after: LabValue | null
  speaker_error: string | null; stored: boolean; at: number
}
export interface LabObservationEntry {
  control: LabControl; result: 'changed' | 'no_change' | 'unsure'; note: string | null
  sent: LabValue; after: LabValue | null; speaker_error: string | null; at: number; who: string
}
export interface SpeakerLab {
  host: string
  snapshot: { host: string; at: number; values: LabValues } | null
  current: LabValues
  errors: Record<string, string>
  source_gain: SourceGain[] | null
  last: Partial<Record<LabControl, LabProbe>>
  observations: LabObservationEntry[]
}

/** One equalizer band exactly as the speaker describes it: its own range and step. */
export interface EqBand { band: string; min: number; max: number; step: number; value: number }
export interface EqState {
  bands: EqBand[] | null
  /** equalizerOnOff as the speaker reports it. Read only until its write is verified in the lab. */
  enabled: boolean | null
  errors: Record<string, string>
}

/** Automatic colour cycling, run on the server. */
export interface CycleConfig {
  interval_s: number; mode: 'palette' | 'random'; palette: Rgb[]
  /** Gradual transition: intermediate colours written by the server (not the speaker's own fade). */
  smooth: boolean
}
export interface CycleState {
  config: CycleConfig
  status: {
    running: boolean
    state: 'stopped' | 'running' | 'disconnected' | 'error'
    message: string | null
    last_colour: Rgb | null
    changed_at: number | null
    steps: number
  }
}

/** A personal speaker profile, stored on the server. Volume is present only when include_volume. */
export interface Profile {
  id: string; name: string; include_volume: boolean; created_at: number; updated_at: number
  data: {
    eq: Record<string, number>; bass: number; treble: number; loudness: boolean
    rgb: Rgb; brightness: number; volume?: number
    cycle: { running: boolean; config: CycleConfig }
  }
}
export interface ProfilesState { profiles: Profile[]; loaded_id: string | null; undo: { at: number; from_profile: string | null } | null; loading: boolean }
export interface LoadStep { step: string; label: string; ok: boolean; error: string | null }
export interface LoadResult extends ProfilesState { status: 'full' | 'partial' | 'failed'; steps: LoadStep[] }
