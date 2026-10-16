import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { CapabilityKey, CapabilityState, Command, LogEntry, Mode, Role } from '../types'

export interface Favorite { id: string; number: string; name: string }
/** 'tracked' = emulate +/- and "last" with digits from the channel this app last sent (the box ignores CHANNEL keys). */
export type ChannelStepMode = 'tracked' | 'channel' | 'page' | 'dpad'
export const CHANNEL_KEYS: Record<Exclude<ChannelStepMode, 'tracked'>, [string, string]> = {
  channel: ['CHANNEL_UP', 'CHANNEL_DOWN'],
  page: ['PAGE_UP', 'PAGE_DOWN'],
  dpad: ['DPAD_UP', 'DPAD_DOWN'],
}
export type ToastKind = 'success' | 'error' | 'demo' | 'info'
export interface Toast { id: number; kind: ToastKind; text: string }

interface State {
  mode: Mode
  token: string
  /** Which role's device gets volume commands (buttons and voice). */
  volumeRole: Role
  /** Device shown in each role's remote when there is more than one. */
  selected: Partial<Record<Role, string>>
  digitDelayMs: number
  enterAfterDigits: boolean
  /** instant: every digit is sent the moment it is pressed (like a remote). buffered: type a number, then press send. */
  keypadMode: 'instant' | 'buffered'
  /** Which key pair the HOT box actually uses for channel +/-. Chosen by the user after trying them (Settings). */
  channelStepMode: ChannelStepMode
  favorites: Favorite[]
  /** Capabilities the user verified by observing the real device. Live mode only. */
  liveCaps: Record<string, Partial<Record<CapabilityKey, CapabilityState>>>
  demoCaps: Record<string, Partial<Record<CapabilityKey, CapabilityState>>>
  log: LogEntry[]
  toasts: Toast[]
  lastCommand?: { label: string; outcome: LogEntry['outcome']; at: number }
  set: (p: Partial<State>) => void
  select: (role: Role, deviceId: string) => void
  setCap: (deviceId: string, key: CapabilityKey, value: CapabilityState) => void
  addFavorite: (f: Omit<Favorite, 'id'>) => void
  removeFavorite: (id: string) => void
  pushLog: (e: LogEntry) => void
  /** ids are String(entry.at). */
  removeLog: (ids: string[]) => void
  clearLog: () => void
  toast: (kind: ToastKind, text: string) => void
  dismissToast: (id: number) => void
}

let toastSeq = 0

export const useApp = create<State>()(
  persist(
    (set, get) => ({
      mode: 'demo',
      token: '',
      volumeRole: 'tv',
      selected: {},
      digitDelayMs: 350,
      enterAfterDigits: false, // the box collects digits itself and switches after a short pause; an extra OK can PAUSE the stream
      keypadMode: 'instant',
      channelStepMode: 'tracked',
      favorites: [],
      liveCaps: {},
      demoCaps: {},
      log: [],
      toasts: [],
      set: (p) => set(p),
      select: (role, deviceId) => set({ selected: { ...get().selected, [role]: deviceId } }),
      setCap: (deviceId, key, value) => {
        const field = get().mode === 'live' ? 'liveCaps' : 'demoCaps'
        const cur = get()[field]
        set({ [field]: { ...cur, [deviceId]: { ...cur[deviceId], [key]: value } } })
      },
      addFavorite: (f) => set({ favorites: [...get().favorites, { ...f, id: crypto.randomUUID() }] }),
      removeFavorite: (id) => set({ favorites: get().favorites.filter((f) => f.id !== id) }),
      pushLog: (e) =>
        set({ log: [e, ...get().log].slice(0, 50), lastCommand: { label: e.label, outcome: e.outcome, at: e.at } }),
      removeLog: (ids) => set({ log: get().log.filter((e) => !ids.includes(String(e.at))) }),
      clearLog: () => set({ log: [], lastCommand: undefined }),
      toast: (kind, text) => {
        const id = ++toastSeq
        set({ toasts: [...get().toasts.slice(-2), { id, kind, text }] })
        setTimeout(() => get().dismissToast(id), 3200)
      },
      dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
    }),
    {
      name: 'smart-remote-ai',
      version: 4,
      // v0 defaulted to CHANNEL +/- keys, which the HOT box ignores; v1 stored the volume target as a driver, now a role.
      migrate: (state, version) => {
        const s = { ...(state as Record<string, unknown>) }
        if (version < 1) s.channelStepMode = 'tracked'
        if (version < 4) s.enterAfterDigits = false // v3 forced it on by mistake; it made OK pause the channel
        if (version < 2) { s.volumeRole = s.volumeTarget === 'hot' ? 'box' : 'tv'; delete s.volumeTarget }
        return s as never
      },
      // `demoCaps`, toasts and last command are session-only.
      partialize: (s) => ({
        mode: s.mode, token: s.token, volumeRole: s.volumeRole, selected: s.selected, digitDelayMs: s.digitDelayMs,
        enterAfterDigits: s.enterAfterDigits, keypadMode: s.keypadMode, channelStepMode: s.channelStepMode, favorites: s.favorites, liveCaps: s.liveCaps, log: s.log,
      }),
    },
  ),
)

export type { Command }
