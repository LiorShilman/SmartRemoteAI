import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, Check, Pencil, RefreshCw, Save, Trash2, Undo2, X } from 'lucide-react'
import { Card, Key } from '../ui/Primitives'
import { useApp } from '../../app/store'
import { useBackend } from '../../hooks/useDevices'
import { ApiError, api } from '../../services/api'
import type { CycleState, EqState, LoadResult, Profile, ProfilesState, SpeakerState } from '../../types'

const when = (at: number) => new Date(at * 1000).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' })
const sameRgb = (a?: { red: number; green: number; blue: number } | null, b?: { red: number; green: number; blue: number } | null) =>
  !!a && !!b && a.red === b.red && a.green === b.green && a.blue === b.blue
const near = (a: number | null | undefined, b: number | null | undefined) => a != null && b != null && Math.abs(a - b) < 1e-6

/** Does what the speaker/server report now still match the profile? null = not known yet (data still loading). */
function matches(p: Profile, s?: SpeakerState, eq?: EqState, cy?: CycleState): boolean | null {
  if (!s || !eq?.bands || !cy) return null
  const d = p.data
  const eqOk = eq.bands.every((b) => near(b.value, d.eq[b.band])) && eq.bands.length === Object.keys(d.eq).length
  const c = cy.config, pc = d.cycle.config
  const cycleOk = cy.status.running === d.cycle.running && c.interval_s === pc.interval_s && c.mode === pc.mode && !!c.smooth === !!pc.smooth
    && c.palette.length === pc.palette.length && c.palette.every((x, i) => sameRgb(x, pc.palette[i]))
  return eqOk && cycleOk && near(s.bass, d.bass) && near(s.treble, d.treble) && s.loudness === d.loudness && near(s.brightness, d.brightness)
    && (d.cycle.running || sameRgb(s.rgb, d.rgb)) // while cycling the colour moves on by design
    && (!p.include_volume || near(s.volume, d.volume))
}

/** Personal profiles, stored on the server. Nothing is loaded automatically; loading is a controlled sequence on the
 * server, with an undo snapshot taken first, and a partial load is shown as partial. */
export function SpeakerProfiles({ bare = false }: { bare?: boolean }) {
  const { mode, token, toast } = useApp()
  const backend = useBackend()
  const live = mode === 'live' && backend === 'online'
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['speaker-profiles', token], queryFn: () => api.speakerProfiles(token), enabled: live, refetchInterval: 30_000 })
  // observe (never fetch) what the other cards already read, to tell whether the loaded profile still matches
  const s = useQuery<SpeakerState>({ queryKey: ['speaker', token], enabled: false }).data
  const eq = useQuery<EqState>({ queryKey: ['speaker-eq', token], enabled: false }).data
  const cy = useQuery<CycleState>({ queryKey: ['speaker-cycle', token], enabled: false }).data

  const [name, setName] = useState('')
  const [withVolume, setWithVolume] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [confirmUpdate, setConfirmUpdate] = useState(false)
  const [result, setResult] = useState<(LoadResult & { title: string }) | null>(null)

  if (!live) return null
  // guard the shape: an unexpected reply must not take the home screen down
  const data = q.data && Array.isArray(q.data.profiles) ? q.data : undefined
  const loaded = data?.profiles.find((p) => p.id === data.loaded_id)
  const same = loaded ? matches(loaded, s, eq, cy) : null

  const call = async <T extends ProfilesState>(key: string, fn: () => Promise<T>, after?: (r: T) => void) => {
    setBusy(key)
    try {
      const r = await fn()
      qc.setQueryData(['speaker-profiles', token], r)
      after?.(r)
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'הפעולה נכשלה.')
      void q.refetch()
    } finally { setBusy(null) }
  }
  const resync = () => {
    for (const k of ['speaker', 'speaker-eq', 'speaker-cycle']) void qc.invalidateQueries({ queryKey: [k] }) // read everything back
  }
  const load = (p: Profile) => call('load-' + p.id, () => api.speakerProfileLoad(token, p.id), (r) => { setResult({ ...r, title: p.name }); resync() })
  const update = (p: Profile) => call('update-' + p.id, () => api.speakerProfileUpdate(token, p.id),
    () => { setConfirmUpdate(false); setResult(null); toast('success', `הפרופיל ${p.name} עודכן למצב הנוכחי`); resync() })
  const undo = () => call('undo', () => api.speakerProfileUndo(token), (r) => { setResult({ ...r, title: 'חזרה למצב הקודם' }); resync() })

  return (
    <Card className={`flex flex-col gap-3 flex-1 ${bare ? '!bg-[rgba(8,11,22,.45)] !border-white/10 !shadow-none !backdrop-blur-none !rounded-2xl !p-4' : ''}`}>
      <div className="flex items-center gap-3">
        <div className="grid place-items-center w-10 h-10 rounded-2xl bg-white/5 border border-white/10">
          <Bookmark size={20} className="text-secondary" aria-hidden />
        </div>
        <h3 className="flex-1 font-bold text-lg">פרופילים</h3>
        {loaded && (
          <span className={`chip ${same === false ? 'demo' : same ? 'ok' : ''}`} title="הפרופיל שנטען אחרון">
            <bdi className="max-w-28 truncate">{loaded.name}</bdi>{same === false ? ' · שונה' : same ? ' · תואם' : ''}
          </span>
        )}
      </div>

      {loaded && same === false && (
        <div className="flex items-center gap-2 rounded-xl border border-warn/30 bg-warn/5 px-3 py-2 text-xs">
          <span className="flex-1 text-muted">שינית הגדרות מאז שנטען <bdi className="text-text">{loaded.name}</bdi>.{loaded.include_volume ? ' העוצמה תעודכן גם היא.' : ''}</span>
          {confirmUpdate ? (
            <>
              <Key label={`אשר עדכון ${loaded.name}`} variant="primary" className="h-9 !min-h-9 px-3 text-xs font-bold" aria-busy={busy === 'update-' + loaded.id}
                disabled={busy !== null || data?.loading} onClick={() => void update(loaded)}>
                {busy === 'update-' + loaded.id ? 'מעדכן…' : 'לדרוס?'}
              </Key>
              <Key label="בטל עדכון" className="!min-w-9 !min-h-9 !rounded-full" disabled={busy !== null} onClick={() => setConfirmUpdate(false)}><X size={14} aria-hidden /></Key>
            </>
          ) : (
            <Key label={`עדכן את ${loaded.name} למצב הנוכחי`} className="h-9 !min-h-9 px-3 text-xs font-bold" disabled={busy !== null || data?.loading}
              onClick={() => setConfirmUpdate(true)}>
              <RefreshCw size={14} aria-hidden /> עדכן פרופיל
            </Key>
          )}
        </div>
      )}

      {data?.undo && (
        <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs">
          <span className="flex-1 text-muted">מצב קודם נשמר לפני טעינת <bdi className="text-text">{data.undo.from_profile}</bdi> · {when(data.undo.at)}</span>
          <Key label="חזור למצב הקודם" className="h-9 !min-h-9 px-3 text-xs font-bold" aria-busy={busy === 'undo'} disabled={busy !== null}
            onClick={() => void undo()}>
            <Undo2 size={14} aria-hidden /> {busy === 'undo' ? 'מחזיר…' : 'חזור למצב הקודם'}
          </Key>
        </div>
      )}

      {result && (
        <div role="status" className={`rounded-xl border px-3 py-2 text-xs ${result.status === 'full' ? 'border-secondary/30 bg-secondary/5' : result.status === 'partial' ? 'border-warn/40 bg-warn/5' : 'border-danger/40 bg-danger/5'}`}>
          <div className="flex items-start gap-2">
            <span className="flex-1">
              <b><bdi>{result.title}</bdi>: </b>
              {result.status === 'full' ? 'נטען במלואו ונקרא בחזרה מהרמקול.' : result.status === 'partial' ? 'נטען חלקית בלבד.' : 'לא נטען.'}
            </span>
            <button type="button" aria-label="סגור את תוצאת הטעינה" className="text-muted hover:text-text" onClick={() => setResult(null)}><X size={14} aria-hidden /></button>
          </div>
          {result.status !== 'full' && (
            <>
              <p className="mt-1 text-muted">הצליחו {result.steps.filter((st) => st.ok).length} מתוך {result.steps.length} שלבים. לא הצליחו:</p>
              <ul className="mt-0.5 flex flex-col gap-0.5">
                {result.steps.filter((st) => !st.ok).map((st) => (
                  <li key={st.step} className="text-danger">✗ {st.label}{st.error ? ` — ${st.error}` : ''}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      <form className="flex flex-col gap-2" onSubmit={(e) => {
        e.preventDefault()
        const n = name.trim()
        if (!n) return
        void call('save', () => api.speakerProfileSave(token, n, withVolume), () => { setName(''); setWithVolume(false); toast('success', 'הפרופיל נשמר') })
      }}>
        <input className="input !min-h-11" placeholder="שם לפרופיל חדש" aria-label="שם לפרופיל חדש" maxLength={40} value={name}
          onChange={(e) => setName(e.target.value)} />
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer flex-1">
            <input type="checkbox" className="w-5 h-5" checked={withVolume} onChange={(e) => setWithVolume(e.target.checked)} /> כולל עוצמה
          </label>
          <Key type="submit" label="שמור מצב נוכחי" variant="primary" className="h-11 px-4 font-bold text-sm" disabled={busy !== null || !name.trim()}>
            <Save size={15} aria-hidden /> {busy === 'save' ? 'שומר…' : 'שמור מצב נוכחי'}
          </Key>
        </div>
      </form>

      {data && data.profiles.length === 0 && <p className="text-xs text-muted">עדיין אין פרופילים. כוון את הרמקול ושמור את המצב הנוכחי.</p>}
      {data && data.profiles.length > 0 && (
        <ul className="flex flex-col divide-y divide-white/5" aria-label="פרופילים שמורים">
          {data.profiles.map((p) => (
            <li key={p.id} className="flex items-center gap-2 py-2">
              {editing?.id === p.id ? (
                <form className="flex items-center gap-2 flex-1" onSubmit={(e) => {
                  e.preventDefault()
                  const n = editing.name.trim()
                  if (n) void call('rename-' + p.id, () => api.speakerProfileRename(token, p.id, n), () => setEditing(null))
                }}>
                  <input className="input !min-h-10 flex-1" aria-label={`שם חדש לפרופיל ${p.name}`} maxLength={40} autoFocus value={editing.name}
                    onChange={(e) => setEditing({ id: p.id, name: e.target.value })} />
                  <Key type="submit" label="שמור שם" className="!min-w-10 !min-h-10 !rounded-full" disabled={!editing.name.trim()}><Check size={16} aria-hidden /></Key>
                  <Key label="בטל שינוי שם" className="!min-w-10 !min-h-10 !rounded-full" onClick={() => setEditing(null)}><X size={16} aria-hidden /></Key>
                </form>
              ) : (
                <>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm truncate"><bdi>{p.name}</bdi></div>
                    <div className="text-[11px] text-muted">{p.include_volume ? `כולל עוצמה ${p.data.volume} · ` : ''}{p.data.cycle.running ? 'החלפת צבעים · ' : ''}{when(p.updated_at)}</div>
                  </div>
                  <Key label={`טען את הפרופיל ${p.name}`} variant={p.id === data.loaded_id ? 'default' : 'primary'} className="h-9 !min-h-9 px-3 text-xs font-bold"
                    aria-busy={busy === 'load-' + p.id} disabled={busy !== null || data.loading} onClick={() => void load(p)}>
                    {busy === 'load-' + p.id ? 'טוען…' : 'טען'}
                  </Key>
                  <Key label={`שנה את שם הפרופיל ${p.name}`} className="!min-w-9 !min-h-9 !rounded-full" disabled={busy !== null}
                    onClick={() => { setEditing({ id: p.id, name: p.name }); setConfirmDelete(null) }}>
                    <Pencil size={14} aria-hidden />
                  </Key>
                  {confirmDelete === p.id ? (
                    <Key label={`אשר מחיקת ${p.name}`} variant="danger" className="h-9 !min-h-9 px-2.5 text-xs font-bold" disabled={busy !== null}
                      onClick={() => void call('del-' + p.id, () => api.speakerProfileDelete(token, p.id), () => setConfirmDelete(null))}>
                      למחוק?
                    </Key>
                  ) : (
                    <Key label={`מחק את הפרופיל ${p.name}`} variant="danger" className="!min-w-9 !min-h-9 !rounded-full" disabled={busy !== null}
                      onClick={() => setConfirmDelete(p.id)}>
                      <Trash2 size={14} aria-hidden />
                    </Key>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
