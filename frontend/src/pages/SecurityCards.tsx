import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, ScrollText, ShieldAlert } from 'lucide-react'
import { Card, Key, SectionTitle } from '../components/ui/Primitives'
import { SelectableRow, SelectToolbar, useSelection } from '../components/ui/Selectable'
import { useApp } from '../app/store'
import { ApiError, api } from '../services/api'
import { useBackend } from '../hooks/useDevices'
import type { TokenCreated } from '../types'

/** Who is using this browser: admin (master code) or a per-device code. Unknown yet = treated as admin for display. */
export function useMe() {
  const { mode, token } = useApp()
  const backend = useBackend()
  return useQuery({
    queryKey: ['me', token],
    queryFn: () => api.me(token),
    enabled: mode === 'live' && backend === 'online',
    retry: false,
    staleTime: 60_000,
  })
}
/** False only when we KNOW this is a device code (the server enforces it either way). */
export function useIsAdmin() {
  const mode = useApp((s) => s.mode)
  const me = useMe()
  return mode === 'demo' || me.data?.kind !== 'device'
}

export function ago(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return 'מעולם לא'
  const s = Math.max(0, Math.round(now - ts))
  if (s < 60) return 'לפני רגע'
  if (s < 3600) return `לפני ${Math.round(s / 60)} דקות`
  if (s < 86400) return `לפני ${Math.round(s / 3600)} שעות`
  return `לפני ${Math.round(s / 86400)} ימים`
}

const EVENT: Record<string, [string, 'ok' | 'bad' | 'warn' | '']> = {
  login_failed: ['ניסיון כניסה כושל', 'bad'],
  blocked_ip: ['כתובת נחסמה', 'bad'],
  new_ip: ['כניסה מכתובת חדשה', 'warn'],
  token_created: ['נוצר קוד גישה', 'ok'],
  token_revoked: ['קוד גישה בוטל', 'warn'],
  device_added: ['מכשיר נוסף', 'ok'],
  device_updated: ['מכשיר עודכן', ''],
  device_removed: ['מכשיר הוסר', 'warn'],
  device_paired: ['מכשיר מצומד', 'ok'],
  schedule_created: ['נוצר תזמון', ''],
  command: ['פעולה', ''],
}

function CopyButton({ text, label, toastText }: { text: string; label: string; toastText: string }) {
  const toast = useApp((s) => s.toast)
  const [done, setDone] = useState(false)
  return (
    <Key label={label} className="px-3 h-11 text-sm" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); toast('success', toastText); setTimeout(() => setDone(false), 2000) }
      catch { toast('error', 'ההעתקה נחסמה בדפדפן. סמן את הטקסט והעתק ידנית.') }
    }}>
      {done ? <Check size={16} /> : <Copy size={16} />} {label}
    </Key>
  )
}

/** Per-device access codes: create (shown once), see last use, revoke. Admin only. */
export function SecuritySection() {
  const { token, toast } = useApp()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [created, setCreated] = useState<TokenCreated | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['tokens', token], queryFn: () => api.tokens(token), refetchInterval: 15_000 })
  const fail = (e: unknown, fb: string) => toast('error', e instanceof ApiError ? e.message : fb)
  const revokedIds = (list.data ?? []).filter((t) => t.revoked).map((t) => t.id)
  const sel = useSelection(revokedIds) // only revoked codes can be selected for removal; active ones are revoked first

  const purge = async (ids?: string[]) => {
    try {
      const r = await api.clearTokens(token, ids)
      toast('info', r.removed ? `הוסרו ${r.removed} קודים מבוטלים מהרשימה` : 'אין קודים מבוטלים להסרה')
      void qc.invalidateQueries({ queryKey: ['tokens'] })
    } catch (e) { fail(e, 'ההסרה נכשלה.') }
  }

  const create = async () => {
    if (!name.trim()) return
    try { setCreated(await api.createToken(token, name.trim())); setName(''); void qc.invalidateQueries({ queryKey: ['tokens'] }); void qc.invalidateQueries({ queryKey: ['audit'] }) }
    catch (e) { fail(e, 'יצירת הקוד נכשלה.') }
  }
  const revoke = async (id: string) => {
    try { await api.revokeToken(token, id); setConfirmId(null); toast('info', 'הקוד בוטל. המכשיר שלו התנתק.'); void qc.invalidateQueries({ queryKey: ['tokens'] }); void qc.invalidateQueries({ queryKey: ['audit'] }) }
    catch (e) { fail(e, 'הביטול נכשל.') }
  }
  const loginLink = created ? `${location.origin}${import.meta.env.BASE_URL}#token=${encodeURIComponent(created.token)}` : ''

  return (
    <Card className="flex flex-col gap-4">
      <SectionTitle hint="קוד נפרד לכל טלפון או מחשב. אם מכשיר אובד, מבטלים רק אותו, בלי לגעת בשאר.">
        <span className="inline-flex items-center gap-2"><KeyRound size={18} aria-hidden /> קודי גישה למכשירים</span>
      </SectionTitle>

      {created && (
        <div className="rounded-2xl border border-warn/40 bg-warn/5 p-3 flex flex-col gap-3" role="alert">
          <div className="flex items-start gap-2 text-sm text-warn">
            <ShieldAlert size={18} className="shrink-0 mt-0.5" aria-hidden />
            <span>הקוד של <b>{created.name}</b> מוצג <b>פעם אחת בלבד</b>. העתק אותו עכשיו, אחרת תצטרך ליצור חדש.</span>
          </div>
          <input readOnly className="input ltr text-sm" value={created.token} onFocus={(e) => e.currentTarget.select()} aria-label="הקוד החדש" />
          <div className="flex flex-wrap gap-2">
            <CopyButton text={created.token} label="העתק קוד" toastText="הקוד הועתק" />
            <CopyButton text={loginLink} label="העתק קישור כניסה" toastText="הקישור הועתק. שלח אותו למכשיר היעד." />
            <Key label="סגור" className="px-3 h-11 text-sm" onClick={() => setCreated(null)}>סגור</Key>
          </div>
          <p className="text-xs text-muted">הקישור מגדיר את הקוד במכשיר בלחיצה אחת, והקוד בו לא נשלח לשרת בעת הפתיחה.</p>
        </div>
      )}

      {revokedIds.length > 0 && (
        <SelectToolbar s={sel} total={revokedIds.length} clearAllLabel={`נקה שבוטלו (${revokedIds.length})`} deleteLabel="הסר"
          onDeleteSelected={(ids) => purge(ids)} onClearAll={() => purge()} />
      )}
      <ul className="flex flex-col gap-2">
        {list.isPending && <li className="text-sm text-muted">טוען…</li>}
        {list.data?.length === 0 && <li className="text-sm text-muted">עדיין לא נוצרו קודים. כרגע כולם נכנסים עם הקוד הראשי.</li>}
        {list.data?.map((t) => (
          <SelectableRow key={t.id} s={t.revoked ? sel : { ...sel, on: false }} id={t.id}
            className={`rounded-2xl border border-white/5 bg-white/[0.03] p-3 ${t.revoked ? 'opacity-60' : ''}`}>
            <div className="flex-1 min-w-0 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold break-words">{t.name}</div>
                <div className="text-xs text-muted"><bdi className="ltr">{t.prefix}…</bdi></div>
              </div>
              <span className={`chip ${t.revoked ? 'bad' : 'ok'}`}>{t.revoked ? 'בוטל' : 'פעיל'}</span>
            </div>
            <div className="text-xs text-muted">
              שימוש אחרון: {ago(t.last_used_at)}{t.last_ip ? <> · <bdi>{t.last_ip}</bdi></> : null}
            </div>
            {!t.revoked && (confirmId === t.id ? (
              <div className="flex gap-2">
                <Key label={`אשר ביטול ${t.name}`} variant="danger" className="px-4 h-11 text-sm font-bold" onClick={() => void revoke(t.id)}>לבטל את הקוד?</Key>
                <Key label="ביטול" className="px-4 h-11 text-sm" onClick={() => setConfirmId(null)}>השאר</Key>
              </div>
            ) : (
              <Key label={`בטל את הקוד של ${t.name}`} className="px-4 h-11 text-sm self-start" onClick={() => setConfirmId(t.id)}>בטל קוד</Key>
            ))}
            </div>
          </SelectableRow>
        ))}
      </ul>

      <form className="flex gap-2 pt-2 border-t border-white/5" onSubmit={(e) => { e.preventDefault(); void create() }}>
        <input className="input flex-1" placeholder="שם המכשיר (למשל: הטלפון של דנה)" aria-label="שם הקוד החדש"
          maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
        <Key label="צור קוד" variant="primary" className="px-4 h-12 text-sm" type="submit" disabled={!name.trim()}>צור קוד</Key>
      </form>
    </Card>
  )
}

/** Recent security-relevant events (logins that failed, new locations, device and access changes). Admin only. */
export function AuditSection() {
  const { token } = useApp()
  const log = useQuery({ queryKey: ['audit', token], queryFn: () => api.audit(token, 40), refetchInterval: 15_000 })
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle hint="אירועי אבטחה ושינויים חשובים. לא נשמרים בו קודים או סודות.">
        <span className="inline-flex items-center gap-2"><ScrollText size={18} aria-hidden /> יומן פעילות</span>
      </SectionTitle>
      {log.isPending ? <p className="text-sm text-muted">טוען…</p> : log.data?.length === 0 ? (
        <p className="text-sm text-muted">אין אירועים עדיין.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-white/5 max-h-96 overflow-y-auto thin-scroll ps-3">
          {log.data?.map((a) => {
            const [label, tone] = EVENT[a.event] ?? [a.event, '']
            return (
              <li key={a.id} className="py-2 flex flex-col gap-1 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className={`chip ${tone}`}>{label}</span>
                  <span className="text-xs text-muted">{ago(a.at)}</span>
                </div>
                {a.detail && <div className="break-words text-muted text-xs">{a.detail}</div>}
                <div className="text-xs text-muted"><bdi>{a.who}</bdi> · <bdi>{a.ip}</bdi></div>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
