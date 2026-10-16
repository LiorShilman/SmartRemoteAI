import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Link2, Pencil, Radar, Trash2 } from 'lucide-react'
import { Card, CapChip, Key, SectionTitle } from '../components/ui/Primitives'
import { CHANNEL_KEYS, useApp, type ChannelStepMode } from '../app/store'
import { ApiError, api } from '../services/api'
import { useBackend, useDevices, useRole } from '../hooks/useDevices'
import { AuditSection, SecuritySection, useIsAdmin, useMe } from './SecurityCards'
import { useSend } from '../hooks/useSend'
import { shortName } from '../services/deviceName'
import { DRIVER_LABEL, ROLE_LABEL } from '../services/roles'
import type { Device, DeviceKind, Role } from '../types'

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-semibold">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  )
}

function ModeSection() {
  const { mode, token, set } = useApp()
  const backend = useBackend()
  const me = useMe()
  const status = {
    demo: ['demo', 'הדגמה'], checking: ['', 'בודק…'], online: ['ok', 'השרת מחובר'],
    offline: ['bad', 'השרת לא זמין'], unauthorized: ['bad', token ? 'קוד גישה שגוי' : 'נדרש קוד גישה'],
  }[backend] as [string, string]
  return (
    <Card className="flex flex-col gap-4">
      <SectionTitle hint="במצב הדגמה הכפתורים מדמים פעולה בלבד. מצב אמיתי דורש Backend פעיל.">מצב עבודה</SectionTitle>
      <div className="grid grid-cols-2 gap-3" role="radiogroup" aria-label="מצב עבודה">
        {(['demo', 'live'] as const).map((m) => (
          <Key key={m} label={m === 'demo' ? 'מצב הדגמה' : 'מצב אמיתי'} variant={mode === m ? 'primary' : 'default'}
            role="radio" aria-checked={mode === m} className="h-12 font-bold" onClick={() => set({ mode: m })}>
            {m === 'demo' ? 'הדגמה' : 'אמיתי'}
          </Key>
        ))}
      </div>
      <span className={`chip self-start ${status[0]}`}>{status[1]}</span>
      {me.data && <p className="text-sm text-muted">מחובר כ: <b className="text-text"><bdi>{me.data.name}</bdi></b>{me.data.kind === 'device' ? ' (גישה למכשיר זה בלבד)' : ' (מנהל)'}</p>}
      {mode === 'live' && (
        <Field label="קוד גישה לשרת" hint="נשמר בדפדפן הזה בלבד. פרטי הצימוד של המכשירים נשארים בשרת.">
          <input className="input ltr" type="password" autoComplete="off" value={token}
            onChange={(e) => set({ token: e.target.value })} />
        </Field>
      )}
    </Card>
  )
}

function PairDialog({ device, onClose }: { device: Device; onClose: () => void }) {
  const { mode, token, toast } = useApp()
  const qc = useQueryClient()
  const [phase, setPhase] = useState<'idle' | 'code'>('idle')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)

  const fail = (e: unknown) => toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
  const start = async () => {
    if (mode === 'demo') { setPhase('code'); return }
    setBusy(true)
    try { await api.pairStart(token, device.id); setPhase('code') } catch (e) { fail(e) } finally { setBusy(false) }
  }
  const confirm = async () => {
    if (mode === 'demo') { toast('demo', 'סימולציה: הצימוד לא בוצע מול מכשיר אמיתי'); onClose(); return }
    setBusy(true)
    try {
      await api.pairConfirm(token, device.id, code.trim())
      toast('success', 'הצימוד הושלם')
      await qc.invalidateQueries({ queryKey: ['devices'] })
      onClose()
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <div className="glass !rounded-2xl p-4 flex flex-col gap-3">
      {phase === 'idle' ? (
        <>
          <p className="text-sm">
            {device.kind === 'hot'
              ? 'לחיצה תפעיל צימוד: ייפתח קוד על מסך הממיר.'
              : 'הטלוויזיה חייבת להיות דלוקה. תופיע בקשת אישור על המסך — אשר אותה.'}
          </p>
          <div className="flex gap-2">
            <Key label="התחל צימוד" variant="primary" className="px-5 h-12" disabled={busy} onClick={() => void start()}>התחל צימוד</Key>
            <Key label="ביטול" className="px-5 h-12" onClick={onClose}>ביטול</Key>
          </div>
        </>
      ) : (
        <>
          {device.kind === 'hot' ? (
            <Field label="הקוד שמופיע על מסך הממיר">
              <input className="input ltr text-center text-xl tracking-widest" value={code} maxLength={8} autoFocus
                onChange={(e) => setCode(e.target.value.toUpperCase())} />
            </Field>
          ) : (
            <p className="text-sm">אשר את הבקשה על מסך הטלוויזיה (בדרך כלל ״אישור״), ואז לחץ על ״אשר״ כאן.</p>
          )}
          <div className="flex gap-2">
            <Key label="אשר צימוד" variant="primary" className="px-5 h-12" disabled={busy || (device.kind === 'hot' && code.length < 4)}
              onClick={() => void confirm()}>אשר</Key>
            <Key label="ביטול" className="px-5 h-12" onClick={onClose}>ביטול</Key>
          </div>
        </>
      )}
    </div>
  )
}

function DeviceRow({ d, live, readOnly = false, onChanged }: { d: Device; live: boolean; readOnly?: boolean; onChanged: () => void }) {
  const { token, toast } = useApp()
  const [pairing, setPairing] = useState(false)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(d.name)
  const [role, setRole] = useState<Role>(d.role)
  const [host, setHost] = useState(d.host ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const fail = (e: unknown, fallback: string) => toast('error', e instanceof ApiError ? e.message : fallback)

  const save = async () => {
    try { await api.updateDevice(token, d.id, { name: name.trim() || undefined, role, ...(host.trim() && host.trim() !== d.host ? { host: host.trim() } : {}) }); setEditing(false); onChanged() }
    catch (e) { fail(e, 'השמירה נכשלה.') }
  }
  const remove = async () => {
    try { await api.removeDevice(token, d.id); toast('info', 'המכשיר הוסר. פרטי הצימוד שלו נמחקו מהשרת.'); onChanged() }
    catch (e) { fail(e, 'המחיקה נכשלה.') }
  }

  return (
    <li className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 rounded-2xl bg-white/[0.03] border border-white/5 p-3">
        <div className="min-w-0">
          <div className="font-semibold break-words"><bdi>{shortName(d)}</bdi></div>
          <div className="text-xs text-muted"><bdi>{ROLE_LABEL[d.role]} · {DRIVER_LABEL[d.kind]} · {d.host ?? '—'}</bdi></div>
        </div>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className={`chip ${d.connection === 'connected' ? 'ok' : d.connection === 'disconnected' ? 'bad' : ''}`}>
            {{ connected: 'מחובר', disconnected: 'מנותק', unpaired: 'לא מצומד' }[d.connection]}
          </span>
          {!readOnly && <div className="flex gap-2">
            <Key label={`ערוך ${shortName(d)}`} className="px-3 h-11 text-sm" disabled={!live} onClick={() => { setEditing(!editing); setConfirmDelete(false) }}>
              <Pencil size={15} /> עריכה
            </Key>
            <Key label={`צמד ${shortName(d)}`} className="px-3 h-11 text-sm" onClick={() => setPairing(!pairing)}>
              <Link2 size={16} /> צימוד
            </Key>
          </div>}
        </div>
      </div>
      {d.last_error && <p className="text-xs text-danger" role="status">{d.last_error}</p>}
      {editing && (
        <div className="glass !rounded-2xl p-4 flex flex-col gap-3">
          <Field label="שם המכשיר">
            <input className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="כתובת IP" hint="השרת מעדכן אותה לבד אם המכשיר קיבל כתובת חדשה. אפשר גם להזין ידנית.">
            <input className="input ltr" inputMode="decimal" value={host} onChange={(e) => setHost(e.target.value)} />
          </Field>
          <div role="radiogroup" aria-label="תפקיד" className="grid grid-cols-2 gap-3">
            {(['tv', 'box'] as const).map((r) => (
              <Key key={r} label={ROLE_LABEL[r]} role="radio" aria-checked={role === r} variant={role === r ? 'primary' : 'default'}
                className="h-11 text-sm font-bold" onClick={() => setRole(r)}>{ROLE_LABEL[r]}</Key>
            ))}
          </div>
          <div className="flex gap-2">
            <Key label="שמור" variant="primary" className="px-5 h-11" onClick={() => void save()}>שמור</Key>
            <Key label="ביטול" className="px-5 h-11" onClick={() => setEditing(false)}>ביטול</Key>
            <span className="flex-1" />
            {!confirmDelete ? (
              <Key label={`הסר ${shortName(d)}`} variant="danger" className="px-3 h-11 text-sm" onClick={() => setConfirmDelete(true)}><Trash2 size={15} /> הסר</Key>
            ) : (
              <Key label="אשר הסרה" variant="danger" className="px-3 h-11 text-sm font-bold" onClick={() => void remove()}>למחוק? לחץ לאישור</Key>
            )}
          </div>
          {confirmDelete && <p className="text-xs text-muted">ההסרה מוחקת גם את הצימוד מהשרת. כדי להשתמש במכשיר שוב צריך להוסיף ולצמד אותו מחדש.</p>}
        </div>
      )}
      {pairing && <PairDialog device={d} onClose={() => setPairing(false)} />}
    </li>
  )
}

function DevicesSection() {
  const { mode, token, toast } = useApp()
  const { devices, backend, refetch } = useDevices()
  const [host, setHost] = useState('')
  const [kind, setKind] = useState<DeviceKind>('lg')
  const [role, setRole] = useState<Role>('tv')
  const [name, setName] = useState('')
  const [scanning, setScanning] = useState(false)
  const live = mode === 'live'
  const offline = live && backend !== 'online'
  const admin = useIsAdmin()

  const scan = async () => {
    setScanning(true)
    try {
      const found = await api.discover(token)
      toast('info', found.length ? `נמצאו ${found.length} מכשירים` : 'לא נמצאו מכשירים. אפשר להזין כתובת IP ידנית.')
      void refetch()
    } catch (e) { toast('error', e instanceof ApiError ? e.message : 'הסריקה נכשלה.') } finally { setScanning(false) }
  }
  const add = async () => {
    if (!/^(\d{1,3}\.){3}\d{1,3}$/.test(host.trim())) { toast('error', 'כתובת IPv4 לא תקינה (למשל 192.168.1.20).'); return }
    try { await api.addDevice(token, kind, host.trim(), role, name.trim() || undefined); setHost(''); setName(''); void refetch() }
    catch (e) { toast('error', e instanceof ApiError ? e.message : 'ההוספה נכשלה.') }
  }
  const pickKind = (k: DeviceKind) => { setKind(k); setRole(k === 'lg' ? 'tv' : 'box') } // sensible default; still changeable

  return (
    <Card className="flex flex-col gap-4 lg:flex-1">
      <SectionTitle hint="טלוויזיות וממירים. סריקה ברשת הביתית, או הזנת כתובת IP ידנית.">מכשירים</SectionTitle>
      <ul className="flex flex-col gap-3">
        {devices.length === 0 && <li className="text-sm text-muted">{offline ? 'אין חיבור לשרת, לכן אי אפשר להציג מכשירים.' : 'לא הוגדרו מכשירים.'}</li>}
        {devices.map((d) => <DeviceRow key={d.id} d={d} live={live && !offline && admin} readOnly={!admin} onChanged={() => void refetch()} />)}
      </ul>
      {admin ? <div className="flex flex-col gap-3 pt-2 border-t border-white/5">
        <Key label="סרוק את הרשת" className="h-12" disabled={!live || offline || scanning} onClick={() => void scan()}>
          <Radar size={18} /> {scanning ? 'סורק…' : 'סרוק רשת'}
        </Key>
        <h3 className="text-sm font-bold pt-1">הוספת מכשיר ידנית</h3>
        <div className="grid grid-cols-2 gap-2">
          <select className="input" aria-label="סוג מכשיר" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="tv">טלוויזיה</option>
            <option value="box">ממיר</option>
          </select>
          <select className="input" aria-label="סוג חיבור" value={kind} onChange={(e) => pickKind(e.target.value as DeviceKind)}>
            <option value="lg">{DRIVER_LABEL.lg}</option>
            <option value="hot">{DRIVER_LABEL.hot}</option>
          </select>
        </div>
        <ul className="text-xs text-muted -mt-1 flex flex-col gap-1" aria-label="הסבר על סוגי החיבור">
          <li><b className="text-text">סוג החיבור</b> קובע איך מדברים עם המכשיר:</li>
          <li>• <bdi className="ltr">LG webOS</bdi> — טלוויזיות של LG</li>
          <li>• <bdi className="ltr">Android TV</bdi> — כל טלוויזיה או ממיר עם <bdi className="ltr">Google TV / Android TV</bdi></li>
        </ul>
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1 min-w-36 ltr" inputMode="decimal" placeholder="192.168.1.20" aria-label="כתובת IP"
            value={host} onChange={(e) => setHost(e.target.value)} />
          <input className="input flex-1 min-w-36" placeholder="שם (לא חובה)" aria-label="שם המכשיר" maxLength={40}
            value={name} onChange={(e) => setName(e.target.value)} />
          <Key label="הוסף מכשיר" className="px-5 h-12" disabled={!live || offline} onClick={() => void add()}>הוסף</Key>
        </div>
        {!live && <p className="text-xs text-muted">סריקה והוספה זמינות במצב אמיתי בלבד.</p>}
      </div> : <p className="text-xs text-muted pt-2 border-t border-white/5">הוספה, עריכה וצימוד של מכשירים זמינים למנהל בלבד.</p>}
    </Card>
  )
}

function DigitTest() {
  const { digitDelayMs, enterAfterDigits, keypadMode, set, setCap } = useApp()
  const { device: hot } = useRole('box')
  const { send, busy } = useSend()
  const state = hot?.capabilities.digits

  const run = (digits: string, label: string) =>
    void send({ target: hot!.kind, deviceId: hot!.id, action: 'digits', params: { digits } }, label)

  return (
    <Card className="flex flex-col gap-4">
      <SectionTitle hint="שלח ספרות לממיר, הסתכל על הטלוויזיה, ואז סמן מה קרה. רק הסימון שלך קובע את סטטוס התמיכה.">
        בדיקת ספרות (ממיר) <CapChip state={state} />
      </SectionTitle>
      <div className="grid grid-cols-3 gap-3 ltr">
        <Key label="שלח 1" className="h-12" disabled={!hot || busy} onClick={() => run('1', 'בדיקה: 1')}>שלח 1</Key>
        <Key label="שלח 2" className="h-12" disabled={!hot || busy} onClick={() => run('2', 'בדיקה: 2')}>שלח 2</Key>
        <Key label="שלח 12" className="h-12" disabled={!hot || busy} onClick={() => run('12', 'בדיקה: 12')}>שלח 12</Key>
      </div>
      <Key label="שלח OK" className="h-12" disabled={!hot || busy}
        onClick={() => void send({ target: hot!.kind, deviceId: hot!.id, action: 'key_press', params: { key: 'DPAD_CENTER' } }, 'בדיקה: OK')}>
        שלח OK
      </Key>
      <div className="grid grid-cols-2 gap-3">
        <Key label="סמן שהערוץ התחלף" className="h-12" disabled={!hot} onClick={() => hot && setCap(hot.id, 'digits', 'supported')}>הערוץ התחלף ✔</Key>
        <Key label="סמן שלא קרה כלום" className="h-12" disabled={!hot} onClick={() => hot && setCap(hot.id, 'digits', 'unsupported')}>לא קרה כלום ✘</Key>
      </div>
      <div className="flex flex-col gap-4 pt-1">
        <Field label={`שהייה בין ספרות: ${digitDelayMs}ms`}>
          <input type="range" min={100} max={1500} step={50} value={digitDelayMs} className="w-full h-6"
            onChange={(e) => set({ digitDelayMs: Number(e.target.value) })} />
        </Field>
        <label className="flex items-center gap-3 text-sm min-h-11">
          <input type="checkbox" className="w-5 h-5 shrink-0" checked={keypadMode === 'instant'}
            onChange={(e) => set({ keypadMode: e.target.checked ? 'instant' : 'buffered' })} />
          הקלדה מיידית: כל ספרה נשלחת ברגע שנלחצת, כמו בשלט רגיל
        </label>
        <label className="flex items-center gap-3 text-sm min-h-11">
          <input type="checkbox" className="w-5 h-5 shrink-0" checked={enterAfterDigits}
            onChange={(e) => set({ enterAfterDigits: e.target.checked })} />
          לשלוח OK אחרי מספר שנשלח כרצף (מועדפים, קול, ערוץ +/−)
        </label>
        <p className="text-xs text-muted -mt-2">
          רוב הממירים מחליפים ערוץ לבד אחרי שנייה. לכן OK נוסף עלול להשהות את השידור (PAUSE). הפעל אותו רק אם הממיר שלך דורש אישור.
        </p>
      </div>
    </Card>
  )
}

const CHANNEL_MODES: { mode: ChannelStepMode; title: string; hint: string }[] = [
  { mode: 'tracked', title: 'לפי מספר (מומלץ)', hint: 'מדמה עליה/ירידה בשליחת מספר הערוץ הבא. עובד כשהספרות עובדות' },
  { mode: 'channel', title: 'מקשי ערוץ', hint: 'CHANNEL +/−  (התקני)' },
  { mode: 'page', title: 'עמוד קודם/הבא', hint: 'PAGE UP / DOWN' },
  { mode: 'dpad', title: 'חצים למעלה/למטה', hint: 'מחליפים ערוץ בזמן צפייה' },
]

function ChannelStepTest() {
  const { channelStepMode, set } = useApp()
  const { device: hot } = useRole('box')
  const { send, busy } = useSend()
  const press = (k: string, label: string, tracked = false, delta = 1) =>
    void send(tracked ? { target: hot!.kind, deviceId: hot!.id, action: 'channel_step', params: { delta } } : { target: hot!.kind, deviceId: hot!.id, action: 'key_press', params: { key: k } }, label)
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle hint="לחץ על כל זוג מקשים, הסתכל על הטלוויזיה, ובחר את מה שמחליף ערוץ. הכפתורים בשלט ישלחו את הבחירה שלך.">
        בדיקת מעבר ערוץ (ממיר)
      </SectionTitle>
      {CHANNEL_MODES.map((m) => {
        const [up, down] = m.mode === 'tracked' ? ['', ''] : CHANNEL_KEYS[m.mode]
        const on = channelStepMode === m.mode
        return (
          <div key={m.mode} className={`rounded-2xl border p-3 flex flex-col gap-2 ${on ? 'border-secondary/60 bg-secondary/5' : 'border-white/10'}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold text-sm">{m.title}</div>
                <div className="text-xs text-muted"><bdi>{m.hint}</bdi></div>
              </div>
              <Key label={`השתמש ב${m.title}`} role="radio" aria-checked={on} variant={on ? 'primary' : 'default'}
                className="px-3 h-10 text-sm" onClick={() => set({ channelStepMode: m.mode })}>{on ? 'נבחר ✔' : 'בחר'}</Key>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Key label={`נסה ${m.title} למעלה`} className="h-11 text-sm" disabled={!hot || busy} onClick={() => press(up, `בדיקה: ${m.title} +`, m.mode === 'tracked', 1)}>ערוץ + ▲</Key>
              <Key label={`נסה ${m.title} למטה`} className="h-11 text-sm" disabled={!hot || busy} onClick={() => press(down, `בדיקה: ${m.title} −`, m.mode === 'tracked', -1)}>ערוץ − ▼</Key>
            </div>
          </div>
        )
      })}
    </Card>
  )
}

function Preferences() {
  const { volumeRole, set } = useApp()
  return (
    <Card>
      <SectionTitle hint="איזה מכשיר מקבל פקודות עוצמה מהכפתורים ומהקול. ההגדרה לא בודקת איזה מכשיר באמת שולט בשמע.">יעד עוצמת קול</SectionTitle>
      <div className="grid grid-cols-2 gap-3" role="radiogroup" aria-label="יעד עוצמת קול">
        {(['tv', 'box'] as const).map((r) => (
          <Key key={r} label={`עוצמה דרך ה${ROLE_LABEL[r]}`} role="radio" aria-checked={volumeRole === r}
            variant={volumeRole === r ? 'primary' : 'default'} className="h-12 font-bold" onClick={() => set({ volumeRole: r })}>
            {ROLE_LABEL[r]}
          </Key>
        ))}
      </div>
    </Card>
  )
}

function Diagnostics() {
  const { log, lastCommand, mode, clearLog, toast } = useApp()
  const backend = useBackend()
  const exportLogs = () => {
    // Only fields from the log entries: never tokens or device credentials.
    const blob = new Blob([JSON.stringify({ mode, backend, log }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'smart-remote-diagnostics.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <Card className="flex flex-col gap-3 lg:flex-1">
      <SectionTitle hint="נתונים ללא סודות. מתאים לשיתוף בעת תיקון תקלה.">אבחון</SectionTitle>
      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-muted">מצב</dt><dd>{mode === 'demo' ? 'הדגמה' : 'אמיתי'}</dd>
        <dt className="text-muted">שרת</dt><dd>{{ demo: 'הדגמה', checking: 'בודק…', online: 'מחובר', offline: 'לא זמין', unauthorized: 'אימות נכשל' }[backend]}</dd>
        <dt className="text-muted">פקודה אחרונה</dt><dd>{lastCommand?.label ?? '—'}</dd>
        <dt className="text-muted">תוצאה</dt><dd>{lastCommand?.outcome ?? '—'}</dd>
      </dl>
      <div className="grid grid-cols-2 gap-3">
        <Key label="ייצא לוגים" className="h-12" onClick={exportLogs}><Download size={18} /> ייצוא לוגים</Key>
        <Key label="נקה לוגים" className="h-12" disabled={log.length === 0 && !lastCommand}
          onClick={() => { clearLog(); toast('info', 'הלוגים נוקו') }}><Trash2 size={18} /> נקה לוגים ({log.length})</Key>
      </div>
    </Card>
  )
}

export default function Settings() {
  const live = useApp((s) => s.mode) === 'live'
  const admin = useIsAdmin()
  const online = useBackend() === 'online'
  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-2xl font-extrabold">הגדרות</h1>
      <div className="grid gap-5 grid-cols-[minmax(0,1fr)] lg:grid-cols-2 items-stretch">
        <div className="flex flex-col gap-5"><ModeSection />{admin && live && online && <SecuritySection />}<DevicesSection /></div>
        <div className="flex flex-col gap-5"><DigitTest /><ChannelStepTest /><Preferences />{admin && live && online && <AuditSection />}<Diagnostics /></div>
      </div>
    </div>
  )
}
