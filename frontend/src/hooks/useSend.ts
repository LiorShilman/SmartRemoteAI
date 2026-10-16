import { useCallback, useState } from 'react'
import { useApp } from '../app/store'
import { api } from '../services/api'
import { demoSend } from '../demo/demoEngine'
import { useDevices } from './useDevices'
import type { Command, CommandOutcome } from '../types'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Expands "digits" into a timed key sequence; everything else is a single command. */
function expand(cmd: Command, enterAfter: boolean): Command[] {
  if (cmd.action !== 'digits') return [cmd]
  const keys = String(cmd.params?.digits ?? '').split('').filter((c) => /\d/.test(c))
  const out: Command[] = keys.map((d) => ({ target: cmd.target, deviceId: cmd.deviceId, action: 'key_press', params: { key: `KEYCODE_${d}` } }))
  if (enterAfter && out.length) out.push({ target: cmd.target, deviceId: cmd.deviceId, action: 'key_press', params: { key: 'DPAD_CENTER' } })
  return out
}

export function useSend() {
  const [busy, setBusy] = useState(false)
  const { devices } = useDevices()

  const send = useCallback(
    async (cmd: Command, label: string, opts: { silent?: boolean } = {}): Promise<CommandOutcome> => {
      const s = useApp.getState()
      if (navigator.vibrate) navigator.vibrate(8) // only ever after an explicit press
      const done = (o: CommandOutcome) => {
        if (!opts.silent) s.pushLog({ at: Date.now(), mode: s.mode, target: cmd.target, deviceId: cmd.deviceId, label, outcome: o.ok ? o.status : o.code })
        if (!opts.silent) {
          if (!o.ok) s.toast('error', o.message)
          else if (o.status === 'simulated') s.toast('demo', `סימולציה: ${label}`)
          else s.toast('success', `נשלח: ${label}`)
        }
        return o
      }

      // Live: the server types the whole number atomically (timed, ordered, stops on first failure).
      // Demo: keep the per-key simulation so the UI feels the same.
      const live = s.mode === 'live'
      const serverTyped = cmd.action === 'digits' || cmd.action === 'channel_step' || cmd.action === 'channel_last'
      const steps = serverTyped && live
        ? [{ ...cmd, params: { ...cmd.params, delay_ms: s.digitDelayMs, enter: s.enterAfterDigits } }]
        : expand(cmd, s.enterAfterDigits)
      if (steps.length === 0) return done({ ok: false, code: 'INVALID_COMMAND', message: 'הפקודה ריקה.' })

      setBusy(true)
      try {
        let last: CommandOutcome = { ok: true, status: 'sent' }
        for (let i = 0; i < steps.length; i++) {
          if (i > 0) await sleep(s.digitDelayMs)
          if (s.mode === 'demo') last = await demoSend(steps[i])
          else {
            const dev = steps[i].deviceId ? devices.find((d) => d.id === steps[i].deviceId) : devices.find((d) => d.kind === steps[i].target)
            if (!dev) return done({ ok: false, code: 'NOT_PAIRED', message: 'המכשיר לא הוגדר. הוסף וצמד אותו בהגדרות.' })
            last = await api.command(s.token, dev.id, steps[i])
          }
          if (!last.ok) break // never continue a half-sent sequence
        }
        return done(last)
      } finally {
        setBusy(false)
      }
    },
    [devices],
  )
  return { send, busy }
}
