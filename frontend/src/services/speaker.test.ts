import { describe, expect, it } from 'vitest'
import { BRIGHTNESS, TREBLE, VOLUME, bandLabel, changeToSend, clamp, hexToRgb, rgbToHex, snapToStep, trebleLabel } from './speaker'

describe('speaker helpers', () => {
  it('sends nothing without a user-picked value or a known current value', () => {
    expect(changeToSend(null, 23)).toBeNull()
    expect(changeToSend(undefined, 23)).toBeNull()
    expect(changeToSend(28, null)).toBeNull() // speaker state unknown: never guess
    expect(changeToSend(Number.NaN, 23)).toBeNull()
  })

  it('sends only a real change', () => {
    expect(changeToSend(23, 23)).toBeNull()
    expect(changeToSend(5.001, 5)).toBeNull()
    expect(changeToSend(28, 23)).toBe(28)
    expect(changeToSend(-2, 0)).toBe(-2)
  })

  it('clamps to the allowed ranges', () => {
    expect(clamp(103, VOLUME.min, VOLUME.max)).toBe(100)
    expect(clamp(-1, VOLUME.min, VOLUME.max)).toBe(0)
    expect(clamp(7, TREBLE.min, TREBLE.max)).toBe(6)
  })

  it('labels treble with a sign', () => {
    expect(trebleLabel(6)).toBe('+6')
    expect(trebleLabel(0)).toBe('0')
    expect(trebleLabel(-3)).toBe('-3')
  })
})

describe('colour helpers', () => {
  it('round-trips hex and rgb', () => {
    expect(rgbToHex({ red: 24, green: 69, blue: 129 })).toBe('#184581')
    expect(hexToRgb('#184581')).toEqual({ red: 24, green: 69, blue: 129 })
    expect(hexToRgb('#ff067e')).toEqual({ red: 255, green: 6, blue: 126 })
  })
  it('rejects anything that is not a full hex colour', () => {
    expect(hexToRgb('red')).toBeNull()
    expect(hexToRgb('#fff')).toBeNull()
  })
  it('brightness clamps to 0..100', () => {
    expect(clamp(110, BRIGHTNESS.min, BRIGHTNESS.max)).toBe(100)
    expect(clamp(-5, BRIGHTNESS.min, BRIGHTNESS.max)).toBe(0)
  })
})

describe('equalizer helpers', () => {
  it('names the bands', () => {
    expect(['60', '250', '1000', '3500', '12000'].map(bandLabel)).toEqual(['60Hz', '250Hz', '1kHz', '3.5kHz', '12kHz'])
  })
  it('snaps to the band step and range the speaker reported', () => {
    expect(snapToStep(1.3, -6, 6, 0.5)).toBe(1.5)
    expect(snapToStep(1.2, -6, 6, 0.5)).toBe(1)
    expect(snapToStep(9, -6, 6, 0.5)).toBe(6)
    expect(snapToStep(-9, -6, 6, 0.5)).toBe(-6)
    expect(snapToStep(0, -6, 6, 0.5)).toBe(0)
    expect(snapToStep(0.31, 0, 1, 0.1)).toBe(0.3)
    expect(snapToStep(0, 1, 5, 1)).toBe(1) // "reset to 0" on a band that cannot be 0 lands on its nearest value
  })
})
