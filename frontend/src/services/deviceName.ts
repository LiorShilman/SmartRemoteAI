import type { Device } from '../types'

/** Display name without the trailing "(ip)" and the generic "Android TV " prefix; the IP has its own line. */
export const shortName = (d: Pick<Device, 'name'>): string =>
  d.name.replace(/\s*\(\d{1,3}(?:\.\d{1,3}){3}\)\s*$/, '').replace(/^Android TV\s+/, '').trim() || d.name
