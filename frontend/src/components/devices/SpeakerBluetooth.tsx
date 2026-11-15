import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bluetooth, BluetoothSearching } from 'lucide-react'
import { Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { ApiError, api } from '../../services/api'

/** Bluetooth pairing. Reading only on load; the one write (open pairing) is sent only on an explicit press, and
 * "visible" is shown only once the speaker itself reports it. While visible there is no button: what a second
 * activation does is not verified, and the speaker closes pairing by itself (5 min, or when a device connects). */
export function SpeakerBluetooth({ enabled }: { enabled: boolean }) {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const q = useQuery({
    queryKey: ['speaker-bt', token], queryFn: () => api.speakerBluetooth(token), enabled, retry: false,
    refetchInterval: (query) => (query.state.data?.discoverable ? 3_000 : 15_000), // follow it closely while visible
  })
  // guard the shape: an unexpected reply must not take the speaker card down
  const bt = q.data && typeof q.data.discoverable === 'boolean' ? { ...q.data, paired: Array.isArray(q.data.paired) ? q.data.paired : [] } : undefined
  const open = async () => {
    if (busy || !bt || bt.discoverable) return
    setBusy(true)
    try {
      const r = await api.speakerPairing(token) // resolves only when the speaker reports discoverable=true
      qc.setQueryData(['speaker-bt', token], r)
      toast('success', `מצב צימוד פתוח: חפש בטלפון "${r.name}"`)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally { setBusy(false) }
  }

  if (!enabled) return null
  if (q.isError) return <p className="text-xs text-danger">לא ניתן לקרוא את מצב ה-Bluetooth של הרמקול.</p>
  if (!bt) return <p className="text-xs text-muted">{q.isPending ? 'קורא מצב Bluetooth…' : 'מצב ה-Bluetooth לא זמין.'}</p>
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        {bt.discoverable
          ? <BluetoothSearching size={18} className="text-secondary shrink-0 animate-pulse" aria-hidden />
          : <Bluetooth size={18} className="text-muted shrink-0" aria-hidden />}
        <div className="flex-1 min-w-0 text-sm">
          {bt.discoverable ? (
            <div role="status">
              <div className="font-semibold text-secondary">גלוי לצימוד בשם <bdi className="ltr">{bt.name}</bdi></div>
              <div className="text-xs text-muted">חפש אותו בהגדרות ה-Bluetooth בטלפון. ייסגר לבד תוך כמה דקות או כשמכשיר יתחבר.</div>
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
        {!bt.discoverable && (
          <Key label="פתח מצב צימוד Bluetooth" className="h-10 px-4 text-sm font-bold shrink-0" aria-busy={busy} disabled={busy} onClick={() => void open()}>
            {busy ? 'פותח…' : 'מצב צימוד'}
          </Key>
        )}
      </div>
      {bt.paired.length > 0 && (
        <div className="text-[11px] text-muted">מצומדים: {[...new Set(bt.paired)].map((n, i) => <span key={n}>{i ? ' · ' : ''}<bdi>{n}</bdi></span>)}</div>
      )}
    </div>
  )
}
