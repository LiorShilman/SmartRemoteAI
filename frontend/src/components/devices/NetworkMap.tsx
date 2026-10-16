import { useEffect, useRef, useState, type ComponentType } from 'react'
import { useNavigate } from 'react-router-dom'
import { Router, Satellite, Server, Smartphone, Tv2 } from 'lucide-react'
import { useApp } from '../../app/store'
import { useBackend, type BackendStatus } from '../../hooks/useDevices'
import { shortName } from '../../services/deviceName'
import { ROLE_LABEL, ROLE_PATH } from '../../services/roles'
import type { Device } from '../../types'

type St = 'ok' | 'bad' | 'warn' | 'idle' | 'demo'

const COLOR: Record<St, string> = {
  ok: '#34d399', bad: '#ff667a', warn: '#ffc857', idle: '#70809f', demo: '#a78bfa',
}
const WORD: Record<St, string> = { ok: 'מחובר', bad: 'מנותק', warn: 'ממתין', idle: 'לא מצומד', demo: 'הדגמה' }

interface Node {
  id: string; x: number; y: number
  Icon: ComponentType<{ x?: number; y?: number; width?: number; height?: number; color?: string }>
  title: string; sub?: string; st: St; label: string; href?: string; deviceId?: string
}
interface Link { from: string; to: string; st: St }

const W = 132
const H = 104
const MAX_DEVICES = 8

function backendSt(b: BackendStatus): St {
  return b === 'online' ? 'ok' : b === 'demo' ? 'demo' : b === 'checking' ? 'warn' : 'bad'
}
function deviceSt(d: Device, demo: boolean): St {
  if (demo) return 'demo'
  return d.connection === 'connected' ? 'ok' : d.connection === 'disconnected' ? 'bad' : 'idle'
}

function useWide() {
  const q = '(min-width: 640px)'
  const [wide, setWide] = useState(() => typeof matchMedia !== 'undefined' && matchMedia(q).matches)
  useEffect(() => {
    const m = matchMedia(q)
    const f = () => setWide(m.matches)
    m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [])
  return wide
}

/** Live connection map: this browser -> server -> home network -> every configured device. */
export function NetworkMap({ devices: all }: { devices: Device[] }) {
  const wide = useWide()
  const nav = useNavigate()
  const select = useApp((s) => s.select)
  const backend = useBackend()
  const demo = backend === 'demo'
  const { log } = useApp()
  const devices = [...all].sort((a, b) => (a.role === b.role ? 0 : a.role === 'tv' ? -1 : 1)).slice(0, MAX_DEVICES)

  const bSt = backendSt(backend)
  const devSt = devices.map((d) => deviceSt(d, demo))
  const connected = devSt.filter((s) => s === 'ok').length
  const lanSt: St = demo ? 'demo' : backend !== 'online' ? 'idle' : connected > 0 ? 'ok' : 'warn'

  // Horizontal on wide screens (right -> left in RTL reading order), vertical on phones. Devices stack evenly.
  const n = Math.max(devices.length, 1)
  const rowH = 126
  const rows = Math.ceil(n / 2)
  const vb = wide ? [1000, Math.max(330, n * rowH + 40)] : [360, 618 + (rows - 1) * rowH]
  const mid = wide ? vb[1] / 2 : 0
  const pos = wide
    ? { browser: [880, mid], server: [650, mid], lan: [420, mid] }
    : { browser: [180, 62], server: [180, 200], lan: [180, 338] }
  const devPos = (i: number): [number, number] =>
    wide ? [160, vb[1] / 2 + (i - (n - 1) / 2) * rowH]
      : [n === 1 ? 180 : i % 2 === 0 ? 268 : 92, 528 + Math.floor(i / 2) * rowH]

  const nodes: Node[] = [
    { id: 'browser', x: pos.browser[0], y: pos.browser[1], Icon: Smartphone, title: 'המכשיר שלך', sub: demo ? 'מצב הדגמה' : 'דפדפן', st: demo ? 'demo' : 'ok', label: demo ? 'הדגמה' : 'פעיל' },
    { id: 'server', x: pos.server[0], y: pos.server[1], Icon: Server, title: 'שרת השלט', sub: backend === 'unauthorized' ? 'קוד גישה שגוי' : demo ? 'מדומה' : 'Backend', st: bSt, label: WORD[bSt] },
    { id: 'lan', x: pos.lan[0], y: pos.lan[1], Icon: Router, title: 'רשת ביתית', sub: `${connected}/${devices.length} מכשירים`, st: lanSt, label: lanSt === 'ok' ? 'פעילה' : WORD[lanSt] },
    ...devices.map((d, i): Node => ({
      id: `dev:${d.id}`, x: devPos(i)[0], y: devPos(i)[1], Icon: d.role === 'tv' ? Tv2 : Satellite,
      title: ROLE_LABEL[d.role], sub: shortName(d), st: devSt[i], label: WORD[devSt[i]], href: ROLE_PATH[d.role], deviceId: d.id,
    })),
  ]
  const links: Link[] = [
    { from: 'browser', to: 'server', st: bSt },
    { from: 'server', to: 'lan', st: demo ? 'demo' : backend === 'online' ? 'ok' : 'idle' },
    ...devices.map((d, i): Link => ({ from: 'lan', to: `dev:${d.id}`, st: devSt[i] })),
  ]
  const byId = Object.fromEntries(nodes.map((nd) => [nd.id, nd]))

  // A packet runs along the path of each NEW command: green when sent/simulated, red when it failed.
  const last = log[0]
  const seen = useRef(last?.at)
  const [pulse, setPulse] = useState<{ at: number; to: string; ok: boolean } | null>(null)
  useEffect(() => {
    if (last && last.at !== seen.current) {
      seen.current = last.at
      const target = devices.find((d) => d.id === last.deviceId) ?? devices.find((d) => d.kind === last.target)
      if (target) setPulse({ at: last.at, to: `dev:${target.id}`, ok: last.outcome === 'sent' || last.outcome === 'simulated' })
      const t = setTimeout(() => setPulse(null), 2200)
      return () => clearTimeout(t)
    }
  }, [last]) // eslint-disable-line react-hooks/exhaustive-deps

  const pathBetween = (a: Node, b: Node) => {
    const [x1, y1, x2, y2] = edge(a, b, wide)
    const c = wide ? `C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2},` : `C ${x1} ${(y1 + y2) / 2}, ${x2} ${(y1 + y2) / 2},`
    return `M ${x1} ${y1} ${c} ${x2} ${y2}`
  }
  const chain = pulse && byId[pulse.to] ? ['browser', 'server', 'lan', pulse.to] : []
  const packetPath = chain.slice(1).map((id, i) => pathBetween(byId[chain[i]], byId[id]))

  const summary = `מפת חיבורים: שרת ${WORD[bSt]}, ${devices.map((d, i) => `${ROLE_LABEL[d.role]} ${WORD[devSt[i]]}`).join(', ') || 'אין מכשירים'}`

  return (
    <div className="relative overflow-hidden rounded-[24px] glass p-3 sm:p-4">
      <div aria-hidden className="absolute inset-0 opacity-[.35]"
        style={{ backgroundImage: 'radial-gradient(rgba(166,179,203,.22) 1px, transparent 1px)', backgroundSize: '22px 22px' }} />
      <svg viewBox={`0 0 ${vb[0]} ${vb[1]}`} role="img" aria-label={summary} className="relative w-full h-auto select-none">
        <defs>
          {(Object.keys(COLOR) as St[]).map((k) => (
            <filter key={k} id={`glow-${k}`} x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="5" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          ))}
        </defs>

        {links.map((l) => {
          const d = pathBetween(byId[l.from], byId[l.to])
          const c = COLOR[l.st]
          return (
            <g key={l.from + l.to}>
              <path d={d} fill="none" stroke={c} strokeOpacity={l.st === 'idle' ? 0.35 : 0.22} strokeWidth={8} strokeLinecap="round" />
              <path d={d} fill="none" stroke={c} strokeWidth={2.5} strokeLinecap="round"
                className={l.st === 'ok' || l.st === 'demo' ? 'flow' : ''}
                strokeDasharray={l.st === 'idle' ? '3 9' : l.st === 'bad' ? '2 7' : '7 9'} />
            </g>
          )
        })}

        {pulse && packetPath.length > 0 && (
          <circle key={pulse.at} r="7" fill={pulse.ok ? COLOR.ok : COLOR.bad} filter={`url(#glow-${pulse.ok ? 'ok' : 'bad'})`}>
            {packetPath.map((p, i) => (
              <animateMotion key={i} path={p} dur="0.55s" begin={`${i * 0.55}s`} fill="freeze" />
            ))}
            <animate attributeName="opacity" values="1;1;0" keyTimes="0;0.85;1" dur={`${packetPath.length * 0.55 + 0.4}s`} fill="freeze" />
          </circle>
        )}

        {nodes.map((nd) => {
          const c = COLOR[nd.st]
          const interactive = !!nd.href
          const go = () => { if (nd.deviceId) { const d = devices.find((x) => x.id === nd.deviceId); if (d) select(d.role, d.id) } nav(nd.href!) }
          return (
            <g key={nd.id} transform={`translate(${nd.x - W / 2} ${nd.y - H / 2})`}
              role={interactive ? 'link' : undefined} tabIndex={interactive ? 0 : undefined}
              aria-label={interactive ? `${nd.title}: ${nd.label}. פתח` : undefined}
              onClick={interactive ? go : undefined}
              onKeyDown={interactive ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go() } } : undefined}
              style={{ cursor: interactive ? 'pointer' : 'default', outline: 'none' }}>
              <rect width={W} height={H} rx={20} fill="rgba(17,24,43,.92)" stroke={c} strokeOpacity={0.85} strokeWidth={1.6}
                filter={nd.st === 'idle' ? undefined : `url(#glow-${nd.st})`} />
              <circle cx={W - 16} cy={16} r={5} fill={c} />
              <nd.Icon x={W / 2 - 14} y={14} width={28} height={28} color={c} />
              <text x={W / 2} y={60} textAnchor="middle" fill="#f4f7ff" fontSize="16" fontWeight="700">{nd.title}</text>
              <text x={W / 2} y={78} textAnchor="middle" fill="#a6b3cb" fontSize="11.5">{clip(nd.sub ?? '', 17)}</text>
              <text x={W / 2} y={95} textAnchor="middle" fill={c} fontSize="12" fontWeight="700">{nd.label}</text>
            </g>
          )
        })}
      </svg>

      <ul className="relative flex flex-wrap gap-x-4 gap-y-1.5 justify-center text-xs text-muted pt-1" aria-label="מקרא">
        {(['ok', 'bad', 'idle', 'warn', 'demo'] as St[]).map((k) => (
          <li key={k} className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: COLOR[k], boxShadow: `0 0 8px ${COLOR[k]}` }} />
            {{ ok: 'מחובר', bad: 'מנותק', idle: 'לא מצומד', warn: 'בבדיקה', demo: 'הדגמה' }[k]}
          </li>
        ))}
      </ul>
    </div>
  )
}

function clip(s: string, n: number) { return s.length > n ? s.slice(0, n - 1) + '…' : s }

/** Start/end points on the node borders, facing each other along the layout axis. */
function edge(a: Node, b: Node, wide: boolean): [number, number, number, number] {
  if (wide) return [a.x - W / 2, a.y, b.x + W / 2, b.y] // layout runs right -> left
  return [a.x, a.y + H / 2, b.x, b.y - H / 2]
}
