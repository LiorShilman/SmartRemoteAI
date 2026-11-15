/** B&W Zeppelin: value ranges and the "should this be sent?" rule, kept pure so they can be unit-tested.
 * The server validates the same ranges again; these only shape the UI. */

/** The speaker's own units, shown as is (chosen by the user): `player:volume` declares a slider 0..50 step 1
 * (volumeMap has 51 entries, -120..0 dB; 1 dB per step above 10). */
export const VOLUME = { min: 0, max: 50, step: 1, button: 1 } as const
/** Bass and treble: both nodes declare a slider -10..+10 dB in steps of 0.5. Treble 7 was written and read back and 11
 * came back clamped to 10; whether values beyond 6 change the sound is not verified. Bass rests on the metadata alone. */
export const TREBLE = { min: -10, max: 10, step: 0.5, button: 0.5 } as const
export const BASS = { min: -10, max: 10, step: 0.5, button: 0.5 } as const
/** Brightness: the speaker stores any value; a percentage, chosen by the user. */
export const BRIGHTNESS = { min: 0, max: 100, step: 1, button: 10 } as const
/** Chosen by the user (the speaker stores any value). Which sign is left/right is unknown: no labels. */
export const BALANCE = { min: -6, max: 6, step: 1, button: 1 } as const

export const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))

/** A change is sent only when the user picked a value that differs from what the speaker reported.
 * Loading the screen, refreshing or polling never produces one. */
export function changeToSend(draft: number | null | undefined, current: number | null | undefined): number | null {
  if (draft == null || current == null || !Number.isFinite(draft)) return null
  return Math.abs(draft - current) < 0.01 ? null : draft
}

export const trebleLabel = (v: number) => (v > 0 ? `+${v}` : String(v))

export interface Rgb { red: number; green: number; blue: number }
export const rgbToHex = (c: Rgb) => '#' + [c.red, c.green, c.blue].map((n) => n.toString(16).padStart(2, '0')).join('')
export function hexToRgb(h: string): Rgb | null {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(h)
  return m ? { red: parseInt(m[1], 16), green: parseInt(m[2], 16), blue: parseInt(m[3], 16) } : null
}

/** "60" -> "60Hz", "1000" -> "1kHz", "3500" -> "3.5kHz" (the band names the speaker uses are Hz). */
export function bandLabel(band: string): string {
  const hz = Number(band)
  if (!Number.isFinite(hz)) return band
  return hz >= 1000 ? `${hz / 1000}kHz` : `${hz}Hz`
}

/** Nearest value inside [min, max] that lands on min + k*step: the band's own limits, as the speaker reports them. */
export function snapToStep(v: number, min: number, max: number, step: number): number {
  const k = Math.round((clamp(v, min, max) - min) / step)
  const out = clamp(min + k * step, min, max)
  return Math.round(out * 1e6) / 1e6 // no 0.30000000000000004
}
