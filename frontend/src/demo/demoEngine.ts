import type { Command, CommandOutcome, Device } from '../types'

/** Clearly synthetic devices. Used only while Demo Mode is on. */
export const demoDevices = (): Device[] => [
  {
    id: 'demo-hot', kind: 'hot', role: 'box', name: 'ממיר (הדגמה)', connection: 'connected',
    capabilities: { nav: 'supported', channel_step: 'supported', media: 'unknown', digits: 'unknown', volume: 'unknown', mute: 'unknown' },
  },
  {
    id: 'demo-lg', kind: 'lg', role: 'tv', name: 'טלוויזיה (הדגמה)', connection: 'connected',
    capabilities: { nav: 'supported', volume: 'supported', mute: 'supported', power_off: 'supported', inputs: 'supported', apps: 'supported', wol: 'unknown' },
  },
]

export async function demoSend(_cmd: Command): Promise<CommandOutcome> {
  await new Promise((r) => setTimeout(r, 120))
  return { ok: true, status: 'simulated' }
}
