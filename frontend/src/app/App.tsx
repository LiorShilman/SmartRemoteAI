import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { Home, Mic, Satellite, Settings as Cog, Tv2, TriangleAlert } from 'lucide-react'
import { Toasts } from '../components/ui/Primitives'
import { useBackend } from '../hooks/useDevices'
import { useApp } from './store'
import Dashboard from '../pages/Dashboard'
import RemotePage from '../pages/RemotePage'
import VoiceAssistant from '../pages/VoiceAssistant'
import Settings from '../pages/Settings'

const NAV = [
  { to: '/', label: 'בית', Icon: Home },
  { to: '/tv', label: 'טלוויזיה', Icon: Tv2 },
  { to: '/box', label: 'ממיר', Icon: Satellite },
  { to: '/voice', label: 'קול', Icon: Mic },
  { to: '/settings', label: 'הגדרות', Icon: Cog },
]

function StatusBanner() {
  const backend = useBackend()
  const setMode = useApp((s) => s.set)
  if (backend === 'online') return null
  const text = {
    demo: 'מצב הדגמה: הכפתורים מדמים פעולה בלבד ולא שולחים דבר למכשירים אמיתיים.',
    checking: 'בודק חיבור לשרת השלט…',
    offline: 'אין חיבור לשרת השלט. פעולות לא יישלחו עד שמחשב ה-Backend יהיה פעיל באותה רשת.',
    unauthorized: 'נדרש קוד גישה תקין לשרת. הזן אותו במסך ההגדרות.',
  }[backend]
  const demo = backend === 'demo'
  return (
    <div role="status" className={`flex items-center gap-2 px-4 py-2 text-sm border-b ${demo ? 'bg-warn/10 text-warn border-warn/25' : 'bg-danger/10 text-danger border-danger/25'}`}>
      <TriangleAlert size={16} aria-hidden className="shrink-0" />
      <span className="flex-1">{text}</span>
      {backend === 'offline' && (
        <button className="underline font-semibold" onClick={() => setMode({ mode: 'demo' })}>עבור להדגמה</button>
      )}
    </div>
  )
}

export default function App() {
  const loc = useLocation()
  return (
    <div className="min-h-dvh lg:flex lg:flex-row">
      <div className="aurora" aria-hidden />

      {/* Desktop sidebar: first flex child sits on the right in RTL */}
      <aside className="hidden lg:flex flex-col gap-2 w-60 shrink-0 p-5 sticky top-0 h-dvh border-s border-white/5">
        <div className="mb-6">
          <div className="text-xl font-extrabold tracking-wide ltr">SMART REMOTE</div>
          <div className="text-xs text-muted">סלון</div>
        </div>
        {NAV.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => `flex items-center gap-3 px-4 min-h-12 rounded-2xl no-underline text-text ${isActive ? 'bg-white/10 font-bold' : 'text-muted hover:bg-white/5'}`}>
            <Icon size={20} aria-hidden /> {label}
          </NavLink>
        ))}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <StatusBanner />
        <header className="lg:hidden flex items-center justify-between px-4 pt-4">
          <div>
            <div className="text-lg font-extrabold tracking-wide ltr">SMART REMOTE</div>
            <div className="text-xs text-muted">סלון</div>
          </div>
        </header>
        <main className="flex-1 w-full max-w-5xl mx-auto px-4 pt-4"
          style={{ paddingBottom: 'calc(var(--nav-h) + var(--safe-b) + 28px)' }}>
          <AnimatePresence mode="wait">
            <motion.div key={loc.pathname} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
              <Routes location={loc}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/tv" element={<RemotePage role="tv" />} />
                <Route path="/box" element={<RemotePage role="box" />} />
                <Route path="/lg" element={<Navigate to="/tv" replace />} />
                <Route path="/hot" element={<Navigate to="/box" replace />} />
                <Route path="/voice" element={<VoiceAssistant />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <nav aria-label="ניווט ראשי"
        className="lg:hidden fixed bottom-0 inset-x-0 z-40 glass !rounded-b-none !rounded-t-3xl grid grid-cols-5 px-2"
        style={{ height: 'calc(var(--nav-h) + var(--safe-b))', paddingBottom: 'var(--safe-b)' }}>
        {NAV.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => `flex flex-col items-center justify-center gap-1 text-xs no-underline min-h-11 ${isActive ? 'text-secondary font-bold' : 'text-muted'}`}>
            <Icon size={22} aria-hidden /> {label}
          </NavLink>
        ))}
      </nav>
      <Toasts />
    </div>
  )
}
