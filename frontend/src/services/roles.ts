import type { Device, DeviceKind, Role } from '../types'

export const ROLE_LABEL: Record<Role, string> = { tv: 'טלוויזיה', box: 'ממיר' }
export const ROLE_PATH: Record<Role, string> = { tv: '/tv', box: '/box' }
/** Technical connection types, shown as a subtitle and in the add-device form. */
export const DRIVER_LABEL: Record<DeviceKind, string> = { lg: 'LG webOS', hot: 'Android TV' }

export const byRole = (devices: Device[], role: Role): Device[] => devices.filter((d) => d.role === role)
