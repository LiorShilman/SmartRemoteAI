import { useDevices } from './useDevices'
import { useSend } from './useSend'
import type { CapabilityKey, Command, Device } from '../types'

/** Shared wiring for a remote panel: capability gating and sending to this exact device. */
export function useRemote(device: Device | undefined) {
  const { backend } = useDevices()
  const { send, busy } = useSend()
  const connected = device?.connection === 'connected'
  /** A key is usable when the device is connected and the capability is not known-unsupported. */
  const can = (cap: CapabilityKey) => connected && device?.capabilities[cap] !== 'unsupported'
  // Commands for this panel's own device are pinned to its id; commands for another device (e.g. volume) bring their own.
  const press = (cmd: Command, label: string) =>
    void send({ ...cmd, deviceId: cmd.deviceId ?? (device && cmd.target === device.kind ? device.id : undefined) }, label)

  let blocked: string | null = null
  if (backend === 'offline' || backend === 'unauthorized') blocked = 'אין חיבור לשרת השלט — הכפתורים כבויים.'
  else if (!device) blocked = 'המכשיר עדיין לא הוגדר. הוסף אותו במסך ההגדרות.'
  else if (device.connection === 'unpaired') blocked = 'המכשיר לא מצומד. צמד אותו במסך ההגדרות.'
  else if (!connected) blocked = 'המכשיר מנותק — הכפתורים כבויים.'

  return { device, backend, send, busy, press, can, connected, blocked }
}
