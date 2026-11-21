import { describe, expect, it } from 'vitest'
import { zeppelinIsTvOutput } from './TvAudio'
import type { SpeakerBluetooth, SpeakerSources, TvAudio } from '../../types'

const audio = (o: Partial<TvAudio> = {}): TvAudio => ({ state: 'ready', output: 'bt_soundbar', output_kind: 'bluetooth', output_label: 'x', tv_volume: 70, tv_muted: false, ...o })
const bt = (connected_device: string | null): SpeakerBluetooth => ({ name: 'Z', discoverable: false, pairable: false, connected_device, paired: [] })
const src = (active: string): SpeakerSources => ({ sources: ['spdif', 'bluetooth', 'airplay'].map((id) => ({ id, title: id, active: id === active, plugged: true, available: true })) })

describe('zeppelinIsTvOutput', () => {
  it('needs all three: TV on Bluetooth, speaker playing Bluetooth, speaker connected to the TV', () => {
    expect(zeppelinIsTvOutput(audio(), bt('LG TV[TV]'), src('bluetooth'))).toBe(true)
  })
  it('a Bluetooth output is not assumed to be the speaker', () => {
    expect(zeppelinIsTvOutput(audio(), bt('POCO X7 Pro'), src('bluetooth'))).toBe(false) // speaker plays a phone
    expect(zeppelinIsTvOutput(audio(), bt(null), src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(audio(), bt('LG TV[TV]'), src('airplay'))).toBe(false) // TV paired, but speaker plays AirPlay
  })
  it('TV speakers, offline, pending or unreadable speaker data are never verified', () => {
    expect(zeppelinIsTvOutput(audio({ output: 'tv_speaker', output_kind: 'tv_speaker' }), bt('LG TV[TV]'), src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(audio({ state: 'offline' }), bt('LG TV[TV]'), src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(audio({ state: 'pending' }), bt('LG TV[TV]'), src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(null, bt('LG TV[TV]'), src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(audio(), undefined, src('bluetooth'))).toBe(false)
    expect(zeppelinIsTvOutput(audio(), bt('LG TV[TV]'), undefined)).toBe(false)
    expect(zeppelinIsTvOutput(audio(), bt('LG TV[TV]'), { sources: 'x' } as unknown as SpeakerSources)).toBe(false)
  })
})
