import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bluetooth, BluetoothOff, BluetoothSearching, Monitor, Smartphone, Speaker, Tv2, X } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'
import type { SpeakerBtDevice } from '../../types'

/** m:ss */
export const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.max(0, sec % 60)).padStart(2, '0')}`

const deviceIcon = (d: SpeakerBtDevice) =>
  /tv/i.test(d.name) ? Tv2 : d.roles.includes('speaker') || /desktop|laptop|pc|mac/i.test(d.name) ? Monitor
    : d.roles.includes('input') ? Smartphone : Speaker

/** Bluetooth pairing. Reading only on load; a write is sent only on an explicit press (open pairing; unpair after a
 * second confirming press), and every result shown is what the speaker itself reports afterwards. While visible there
 * is no pairing button: what a second activation does is not verified, and the speaker closes pairing by itself. */
export function SpeakerBluetooth({ enabled }: { enabled: boolean }) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null) // device id awaiting a confirming press
  const [removing, setRemoving] = useState<string | null>(null)
  const [deadline, setDeadline] = useState<number | null>(null) // only when WE opened pairing: then the start is known
  const [closed, setClosed] = useState(false) // pairing was seen open and the speaker has closed it since
  const [now, setNow] = useState(() => Date.now())
  const q = useQuery({
    queryKey: ['speaker-bt', token], queryFn: () => api.speakerBluetooth(token), enabled, retry: false,
    refetchInterval: (query) => (query.state.data?.discoverable ? 3_000 : 15_000), // follow it closely while visible
  })
  // guard the shape: an unexpected reply must not take the speaker card down
  const bt = q.data && typeof q.data.discoverable === 'boolean'
    ? { ...q.data, paired: Array.isArray(q.data.paired) ? q.data.paired : [], devices: Array.isArray(q.data.devices) ? q.data.devices : null }
    : undefined
  const visible = !!bt?.discoverable
  const hasBt = !!bt

  // open -> closed, as the speaker reports it (timeout, a device connected, or closed elsewhere)
  const wasOpen = useRef(false)
  useEffect(() => {
    if (!hasBt) return
    if (wasOpen.current && !visible) { setClosed(true); setDeadline(null) }
    if (visible) setClosed(false)
    wasOpen.current = visible
  }, [hasBt, visible])
  // the countdown ticks only while there is one to show
  useEffect(() => {
    if (!visible || deadline == null) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [visible, deadline])

  const open = async () => {
    if (busy || !bt || bt.discoverable) return
    setBusy(true)
    try {
      const r = await api.speakerPairing(token) // resolves only when the speaker reports discoverable=true
      qc.setQueryData(['speaker-bt', token], r)
      if (r.sent && r.pairing_seconds) { setDeadline(Date.now() + r.pairing_seconds * 1000); setNow(Date.now()) }
      toast('success', `מצב צימוד פתוח: חפש בטלפון "${r.name}"`)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally { setBusy(false) }
  }
  const unpair = async (d: SpeakerBtDevice) => {
    if (removing) return
    setRemoving(d.id)
    try {
      const r = await api.speakerUnpair(token, d.id) // resolves only once the speaker no longer lists it as paired
      qc.setQueryData(['speaker-bt', token], r)
      toast('success', `בוטל הצימוד של ${r.unpaired ?? d.name}`)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally { setRemoving(null); setConfirming(null) }
  }

  if (!enabled) return null
  if (q.isError) return <p className="text-xs text-danger">לא ניתן לקרוא את מצב ה-Bluetooth של הרמקול.</p>
  if (!bt) return <p className="text-xs text-muted">{q.isPending ? 'קורא מצב Bluetooth…' : 'מצב ה-Bluetooth לא זמין.'}</p>
  const left = deadline != null ? Math.max(0, Math.round((deadline - now) / 1000)) : null
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        {visible
          ? <BluetoothSearching size={18} className="text-secondary shrink-0 animate-pulse" aria-hidden />
          : <Bluetooth size={18} className="text-muted shrink-0" aria-hidden />}
        <div className="flex-1 min-w-0 text-sm">
          {visible ? (
            <div role="status">
              <div className="font-semibold text-secondary">גלוי לצימוד בשם <bdi className="ltr">{bt.name}</bdi></div>
              <div className="text-xs text-muted">
                חפש אותו בהגדרות ה-Bluetooth בטלפון.{' '}
                {left != null && left > 0
                  ? <>ייסגר בעוד <span className="ltr tabular-nums font-semibold text-text" aria-label={`${Math.ceil(left / 60)} דקות`}>{mmss(left)}</span>, או כשמכשיר יתחבר.</>
                  : 'ייסגר לבד תוך כמה דקות או כשמכשיר יתחבר.'}
              </div>
            </div>
          ) : (
            <>
              <div className="font-semibold">צימוד מכשיר חדש</div>
              <div className="text-xs text-muted truncate">
                {bt.connected_device ? <>מחובר עכשיו: <bdi>{bt.connected_device}</bdi></> : 'אין מכשיר מחובר'}
              </div>
            </>
          )}
        </div>
        {!visible && (
          <Key label="פתח מצב צימוד Bluetooth" className="h-10 px-4 text-sm font-bold shrink-0" aria-busy={busy} disabled={busy} onClick={() => void open()}>
            {busy ? 'פותח…' : 'מצב צימוד'}
          </Key>
        )}
      </div>
      {left != null && left > 0 && visible && (
        <div className="h-1 rounded-full bg-white/[.06] overflow-hidden" aria-hidden>
          <div className="h-full bg-secondary/60 transition-[width] duration-1000 ease-linear"
            style={{ width: `${(left / (q.data?.pairing_seconds || left)) * 100}%` }} />
        </div>
      )}
      {closed && !visible && (
        <p role="status" className="text-xs text-warn">
          חלון הצימוד נסגר{bt.connected_device ? <> – <bdi>{bt.connected_device}</bdi> מחובר.</> : '. כדי לצמד טלפון, לחץ שוב על "מצב צימוד" ואז צמד מיד מהטלפון.'}
        </p>
      )}

      {bt.devices ? (
        bt.devices.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="text-[11px] font-bold text-muted">מכשירים מצומדים</div>
            <ul className="flex flex-col gap-1.5" aria-label="מכשירים מצומדים">
              {bt.devices.map((d) => {
                const Icon = deviceIcon(d)
                const connected = !!bt.connected_device && bt.connected_device === d.name
                const asking = confirming === d.id
                return (
                  <li key={d.id} className="flex items-center gap-2.5 rounded-xl border border-white/[.07] bg-white/[.02] px-3 py-2 text-sm">
                    <Icon size={15} className={connected ? 'text-secondary shrink-0' : 'text-muted shrink-0'} aria-hidden />
                    <span className="flex-1 min-w-0 truncate">
                      <bdi>{d.name}</bdi>
                      {connected && <span className="text-[11px] text-secondary ms-2">מחובר</span>}
                    </span>
                    {asking ? (
                      <span className="flex items-center gap-1.5 shrink-0">
                        <Key variant="danger" label={`אשר ביטול צימוד של ${d.name}`} className="h-8 px-3 text-xs font-bold"
                          aria-busy={removing === d.id} disabled={!!removing} onClick={() => void unpair(d)}>
                          {removing === d.id ? 'מבטל…' : 'בטל צימוד'}
                        </Key>
                        <Key label="השאר מצומד" className="h-8 px-3 text-xs" disabled={!!removing} onClick={() => setConfirming(null)}>
                          השאר
                        </Key>
                      </span>
                    ) : (
                      <Key label={`בטל צימוד של ${d.name}`} className="!min-w-8 !min-h-8 !rounded-full shrink-0" disabled={!!removing}
                        onClick={() => setConfirming(d.id)}>
                        <X size={14} aria-hidden />
                      </Key>
                    )}
                  </li>
                )
              })}
            </ul>
            {confirming && (
              <p className="text-[11px] text-muted">
                <BluetoothOff size={11} className="inline me-1" aria-hidden />
                ביטול צימוד מוחק את המכשיר מהרמקול{bt.devices.some((d) => d.id === confirming && d.name === bt.connected_device) ? ' ומנתק אותו עכשיו' : ''}. כדי להשתמש בו שוב צריך לצמד מחדש.
              </p>
            )}
          </div>
        )
      ) : bt.paired.length > 0 && (
        <div className="text-[11px] text-muted">מצומדים: {[...new Set(bt.paired)].map((n, i) => <span key={n}>{i ? ' · ' : ''}<bdi>{n}</bdi></span>)}</div>
      )}
    </div>
  )
}
