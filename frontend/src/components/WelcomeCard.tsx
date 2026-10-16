import { Link } from 'react-router-dom'
import { BookOpen, MousePointerClick, Radar, X } from 'lucide-react'
import { Card } from './ui/Primitives'
import { useApp } from '../app/store'

/** One-time welcome on the home screen. A card (not a blocking dialog) so nothing is in the way; the "?" stays in the header. */
export function WelcomeCard() {
  const seen = useApp((s) => s.introSeen)
  const set = useApp((s) => s.set)
  if (seen) return null
  const done = () => set({ introSeen: true })
  return (
    <Card className="relative border-accent/40">
      <button type="button" aria-label="סגור את ההודעה" onClick={done}
        className="absolute top-3 end-3 grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-white/10"><X size={18} /></button>
      <h2 className="text-lg font-bold pe-10">ברוכים הבאים 👋</h2>
      <p className="text-sm text-muted mt-1">שלט אחד לטלוויזיה ולממיר. שלושה דברים להתחיל:</p>
      <ol className="mt-3 flex flex-col gap-2.5 text-sm">
        <li className="flex items-start gap-3"><Radar size={18} className="mt-0.5 shrink-0 text-secondary" aria-hidden /><span><b>המפה</b> מראה מה מחובר: ירוק מחובר, אדום מנותק.</span></li>
        <li className="flex items-start gap-3"><MousePointerClick size={18} className="mt-0.5 shrink-0 text-secondary" aria-hidden /><span>לוחצים על <b>טלוויזיה</b> או <b>ממיר</b> למטה ומתחילים לשלוט.</span></li>
        <li className="flex items-start gap-3"><BookOpen size={18} className="mt-0.5 shrink-0 text-secondary" aria-hidden /><span>כפתור <b>?</b> בראש המסך פותח מדריך מצויר, בכל רגע.</span></li>
      </ol>
      <div className="mt-4 flex flex-wrap gap-3">
        <Link to="/help" onClick={done} className="key primary px-5 h-11 text-sm font-bold no-underline text-white">פתח את המדריך</Link>
        <button type="button" className="key px-5 h-11 text-sm" onClick={done}>הבנתי, תודה</button>
      </div>
    </Card>
  )
}
