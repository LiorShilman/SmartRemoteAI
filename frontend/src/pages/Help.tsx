import { useState, type ReactNode } from 'react'
import {
  Baby, ChevronDown, CirclePlay, Clapperboard, EllipsisVertical, Home, Menu, Mic, Music, Search, Share, Undo2, Volume2, Wifi,
} from 'lucide-react'
import { Card } from '../components/ui/Primitives'

/* ------------------------------------------------------------------ small building blocks */

/** A phone frame to draw a mini version of a screen in. Decorative: every picture has a text legend next to it. */
function Phone({ children, caption }: { children: ReactNode; caption: string }) {
  return (
    <figure className="mx-auto w-60 shrink-0" aria-label={caption}>
      <div aria-hidden className="rounded-[30px] border-2 border-white/20 bg-bg p-2 shadow-[0_10px_40px_rgba(0,0,0,.5)]">
        <div className="mx-auto mb-2 h-1.5 w-14 rounded-full bg-white/15" />
        <div className="rounded-2xl bg-surface/80 p-3 min-h-56 relative">{children}</div>
      </div>
      <figcaption className="mt-2 text-center text-xs text-muted">{caption}</figcaption>
    </figure>
  )
}

/** Numbered marker placed on a picture; the same number appears in the legend below it. */
function Dot({ n, className = '' }: { n: number; className?: string }) {
  return <span aria-hidden className={`absolute z-10 grid h-5 w-5 place-items-center rounded-full bg-warn text-[11px] font-extrabold text-bg shadow ${className}`}>{n}</span>
}

function Legend({ items }: { items: string[] }) {
  return (
    <ol className="mt-3 flex flex-col gap-1.5 text-sm">
      {items.map((t, i) => (
        <li key={i} className="flex gap-2.5">
          <span aria-hidden className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-warn text-[11px] font-extrabold text-bg">{i + 1}</span>
          <span>{t}</span>
        </li>
      ))}
    </ol>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="flex gap-3">
      <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-extrabold">{n}</span>
      <div className="min-w-0 flex-1">
        <h3 className="font-bold">{title}</h3>
        <div className="mt-2 text-sm text-muted flex flex-col gap-3">{children}</div>
      </div>
    </section>
  )
}

const mini = 'inline-grid place-items-center rounded-xl border border-white/10 bg-gradient-to-b from-[#1c2745] to-[#141d36] text-text'
const C = { ok: '#34d399', bad: '#ff667a', idle: '#70809f', demo: '#a78bfa' }

function Chip({ tone, children }: { tone: 'ok' | 'bad' | 'warn' | 'demo' | ''; children: ReactNode }) {
  return <span className={`chip ${tone}`}>{children}</span>
}

/* ------------------------------------------------------------------ tabs */

function Start() {
  return (
    <div className="flex flex-col gap-6">
      <Step n={1} title="פותחים את הקישור האישי">
        <div aria-hidden className="mx-auto w-full max-w-xs rounded-2xl rounded-tr-sm bg-[#005c4b]/80 p-3 text-text text-start">
          <div className="text-[11px] text-white/60 mb-1">הודעה מהמנהל</div>
          <div className="text-sm">היי! הנה השלט שלך 👇</div>
          <div className="mt-1 break-all rounded-lg bg-black/25 p-2 text-xs underline ltr">https://…/SmartRemoteAI/#token=sr_…</div>
        </div>
        <p>כל אדם מקבל קישור משלו מהמנהל. הלחיצה עליו מכניסה אתכם אוטומטית, ואין צורך להקליד שום דבר. אם אין לכם קישור, בקשו.</p>
      </Step>

      <Step n={2} title="מוסיפים למסך הבית">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-white/10 p-3">
            <div className="font-semibold text-text mb-2">אייפון (Safari)</div>
            <div aria-hidden className="flex items-center gap-2"><span className={`${mini} h-9 w-9`}><Share size={18} /></span><span>←</span><span className="rounded-lg bg-white/10 px-2 py-1 text-xs text-text">הוסף למסך הבית</span></div>
            <p className="mt-2 text-xs">לוחצים על כפתור השיתוף ובוחרים "הוסף למסך הבית".</p>
          </div>
          <div className="rounded-2xl border border-white/10 p-3">
            <div className="font-semibold text-text mb-2">אנדרואיד (Chrome)</div>
            <div aria-hidden className="flex items-center gap-2"><span className={`${mini} h-9 w-9`}><EllipsisVertical size={18} /></span><span>←</span><span className="rounded-lg bg-white/10 px-2 py-1 text-xs text-text">התקן אפליקציה</span></div>
            <p className="mt-2 text-xs">פותחים את התפריט ⋮ ובוחרים "התקן אפליקציה".</p>
          </div>
        </div>
      </Step>

      <Step n={3} title="מסך הבית: מפת החיבורים">
        <div aria-hidden className="flex items-center justify-center gap-2 rounded-2xl border border-white/10 bg-bg/60 p-4 text-[11px]">
          {[['המכשיר שלך', C.ok], ['שרת השלט', C.ok], ['רשת ביתית', C.ok]].map(([l, c], i) => (
            <div key={l} className="flex items-center gap-2">
              <div className="rounded-xl border px-2 py-2 text-center" style={{ borderColor: c, boxShadow: `0 0 12px ${c}55` }}>{l}</div>
              {i < 2 && <div className="h-0.5 w-5" style={{ background: c }} />}
            </div>
          ))}
          <div className="flex flex-col gap-2">
            <div className="rounded-xl border px-2 py-1.5" style={{ borderColor: C.ok }}>ממיר</div>
            <div className="rounded-xl border px-2 py-1.5" style={{ borderColor: C.bad }}>טלוויזיה</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Chip tone="ok">ירוק: מחובר</Chip><Chip tone="bad">אדום: מנותק (כבוי או לא ברשת)</Chip><Chip tone="">אפור: עוד לא מצומד</Chip><Chip tone="demo">סגול: הדגמה</Chip>
        </div>
        <p>לוחצים על מכשיר במפה כדי לפתוח את השלט שלו. הנקודה הזזה על הקו היא הפקודה האחרונה שנשלחה.</p>
      </Step>
    </div>
  )
}

function RemoteHelp() {
  return (
    <div className="grid gap-6 md:grid-cols-[15rem_1fr] items-start">
      <Phone caption="השלט (ממיר)">
        <div className="grid grid-cols-3 gap-1.5 relative">
          <Dot n={1} className="-top-2 -start-2" />
          {[Undo2, Menu, Home].map((I, i) => <span key={i} className={`${mini} h-8`}><I size={14} /></span>)}
        </div>
        <div className="relative mx-auto my-3 grid h-24 w-24 place-items-center rounded-full border border-white/10 bg-white/5 text-[10px]">
          <Dot n={2} className="-top-2 -start-3" />
          <span className="absolute top-1">▲</span><span className="absolute bottom-1">▼</span><span className="absolute start-1.5">◀</span><span className="absolute end-1.5">▶</span>
          <span className="grid h-9 w-9 place-items-center rounded-full bg-accent text-xs font-bold">OK</span>
        </div>
        <div className="grid grid-cols-3 gap-1.5 relative ltr">
          <Dot n={3} className="-top-2 -start-2" />
          {['⏪', '⏯', '⏩'].map((x) => <span key={x} className={`${mini} h-7 text-xs`}>{x}</span>)}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-1.5 relative ltr">
          <Dot n={4} className="-top-2 -start-2" />
          {['1', '2', '3', '4', '5', '6'].map((x) => <span key={x} className={`${mini} h-7 text-xs`}>{x}</span>)}
        </div>
        <div className="mt-3 flex items-center justify-center gap-1.5 relative">
          <Dot n={5} className="-top-2 -start-2" />
          <span className={`${mini} h-7 w-12`}><Volume2 size={13} /></span><span className={`${mini} h-7 w-12 text-xs`}>▲ ▼</span>
        </div>
      </Phone>
      <div>
        <h3 className="font-bold mb-1">איך משתמשים בשלט</h3>
        <Legend items={[
          'בית, תפריט וחזור.',
          'חצים לניווט, ו-OK לבחירה.',
          'הרצה אחורה, השהיה והרצה קדימה.',
          'ספרות: כל ספרה נשלחת מיד, כמו בשלט רגיל. הממיר מחבר ספרות רצופות לערוץ. מתחת יש ערוץ +/− ו"אחרון".',
          'עוצמה והשתקה (נשלחות למכשיר שהמנהל בחר).',
        ]} />
        <div className="mt-4 rounded-2xl border border-white/10 p-3 text-sm text-muted">
          <b className="text-text">כפתור "בדיקת חיבור"</b> בראש העמוד בודק שהמכשיר באמת מגיב, ולא רק שהפקודה נשלחה. אם הוא שותק, החיבור מאופס אוטומטית.
        </div>
        <div className="mt-3 rounded-2xl border border-white/10 p-3 text-sm text-muted">
          <b className="text-text">עכבר:</b> בטלוויזיית LG יש מצביע אמיתי על המסך. בממירים יש "משטח החלקה" (בתחתית העמוד) שמדמה עכבר בלחיצות על חצים.
        </div>
      </div>
    </div>
  )
}

function AppsHelp() {
  return (
    <div className="grid gap-6 md:grid-cols-[15rem_1fr] items-start">
      <Phone caption="אפליקציות, מקלדת וחיפוש">
        <div className="relative">
          <Dot n={1} className="-top-2 -start-2" />
          <div className="grid grid-cols-3 gap-1.5 text-[10px]">
            {[[CirclePlay, 'YouTube'], [Clapperboard, 'Netflix'], [Music, 'Spotify']].map(([I, l]) => {
              const Icon = I as typeof Music
              return <span key={l as string} className={`${mini} h-14 flex-col gap-1`}><Icon size={16} />{l as string}</span>
            })}
          </div>
        </div>
        <div className="relative mt-4">
          <Dot n={2} className="-top-2 -start-2" />
          <div className="flex gap-1.5 text-[10px]"><span className="flex-1 rounded-lg border border-white/10 bg-bg px-2 py-2 text-start text-muted">חתולים מצחיקים</span><span className={`${mini} px-2`}><Search size={13} /></span></div>
          <div className="mt-1.5 flex gap-1.5 text-[10px]"><span className="flex-1 rounded-lg bg-accent/30 px-2 py-1.5">YouTube</span><span className="flex-1 rounded-lg bg-white/5 px-2 py-1.5">Netflix</span></div>
        </div>
        <div className="relative mt-4">
          <Dot n={3} className="-top-2 -start-2" />
          <div className="rounded-lg border border-white/10 bg-bg px-2 py-2 text-start text-[10px] text-muted">הקלד כאן…</div>
          <div className="mt-1.5 grid grid-cols-3 gap-1.5 text-[10px]"><span className={`${mini} h-7`}>שלח</span><span className={`${mini} h-7 bg-accent`}>שלח + Enter</span><span className={`${mini} h-7`}>מחק</span></div>
        </div>
      </Phone>
      <div>
        <h3 className="font-bold mb-1">אפליקציות וחיפוש</h3>
        <Legend items={[
          'פותחים אפליקציה במכשיר בלחיצה אחת.',
          'חיפוש ישיר: בוחרים אפליקציה, מקלידים מה לחפש, והיא נפתחת על התוצאות.',
          'הקלדה במסך: מקלידים בטלפון והטקסט מופיע בשדה הפעיל בטלוויזיה (שדה חיפוש וכדומה).',
        ]} />
        <ul className="mt-4 flex flex-col gap-2 text-sm text-muted list-disc ps-5">
          <li>אם אפליקציה לא מותקנת במכשיר, ייפתח דף ההתקנה שלה.</li>
          <li>בטלוויזיית LG נתמך חיפוש ב-YouTube בלבד.</li>
          <li>ההקלדה עובדת רק כשיש שדה טקסט פעיל על המסך.</li>
        </ul>
      </div>
    </div>
  )
}

function VoiceHelp() {
  const says = ['ערוץ 12', 'תגביר', 'השתק', 'פתח נטפליקס בממיר', 'חפש חתולים מצחיקים ביוטיוב', 'תעבור ל-HDMI 2', 'כבה את הטלוויזיה בעוד שעה', 'ערוץ 5 ואז תנמיך']
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3">
        <span aria-hidden className="grid h-14 w-14 place-items-center rounded-full bg-accent shadow-[0_0_30px_rgba(108,107,255,.5)]"><Mic /></span>
        <p className="text-sm text-muted">לחיצה על המיקרופון ודיבור, או הקלדה בשורת הטקסט. ההקלטה מתחילה רק בלחיצה.</p>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="דוגמאות לפקודות">
        {says.map((s) => <span key={s} className="rounded-2xl rounded-es-sm bg-white/8 border border-white/10 px-3 py-2 text-sm">״{s}״</span>)}
      </div>
      <Step n={1} title="רואים תצוגה מקדימה">
        <div aria-hidden className="rounded-2xl border border-white/10 p-3 flex flex-col gap-2 text-xs">
          <div className="rounded-xl bg-white/5 px-3 py-2"><span className="me-2 inline-grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] font-bold">1</span>ממיר: מעבר לערוץ 12</div>
          <div className="rounded-xl bg-white/5 px-3 py-2"><span className="me-2 inline-grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] font-bold">2</span>טלוויזיה: הנמכת עוצמה</div>
          <span className={`${mini} h-9 bg-accent font-bold`}>בצע 2 פעולות</span>
        </div>
        <p>שום דבר לא נשלח לפני שלוחצים "בצע". אם משהו לא הובן, רואים מה לא הובן ולא מבצעים אותו.</p>
      </Step>
      <Step n={2} title="תזמון">
        <p>אפשר להוסיף "בעוד שעה", "בעוד חצי שעה" או "בעוד 20 דקות". הפעולה נשמרת בשרת, גם אם סוגרים את הדפדפן, ואפשר לבטל אותה מהרשימה שמתחת.</p>
      </Step>
    </div>
  )
}

function KidsHelp() {
  return (
    <div className="flex flex-col gap-6">
      <Step n={1} title="מה הילד רואה">
        <div aria-hidden className="rounded-xl border border-secondary/25 bg-secondary/10 px-3 py-2 text-xs text-secondary flex flex-wrap items-center gap-2">
          <Baby size={14} /> מצב ילדים · פתוח עד 21:00 · נשארו 45 דק׳
          <span className={`${mini} ms-auto px-2 py-1 text-[11px] text-text`}>בקש עוד זמן</span>
        </div>
        <p>למעלה בכל מסך: עד מתי מותר וכמה זמן נשאר. מחוץ לשעות, או אחרי המכסה, הכפתורים נחסמים (גם אם מנסים בכוח, השרת עוצר).</p>
      </Step>
      <Step n={2} title="בקשת עוד זמן">
        <div aria-hidden className="flex gap-2 text-xs"><span className={`${mini} px-3 py-1.5`}>15 דק׳</span><span className={`${mini} px-3 py-1.5`}>30 דק׳</span><span className={`${mini} px-3 py-1.5`}>60 דק׳</span></div>
        <p>הילד בוחר כמה, וההורה מקבל התראה (נקודה אדומה על "הגדרות"). האישור מאריך גם את שעת הסיום וגם את המכסה של היום.</p>
      </Step>
      <Step n={3} title="מה ההורה עושה">
        <div aria-hidden className="rounded-xl border border-warn/40 bg-warn/5 p-3 text-xs flex flex-col gap-2">
          <div><b>דנה</b> מבקשת עוד <b>30 דקות</b></div>
          <div className="flex gap-2"><span className={`${mini} bg-accent px-3 py-1.5`}>אשר 30 דק׳</span><span className={`${mini} px-3 py-1.5`}>רק 15</span><span className={`${mini} px-3 py-1.5`}>דחה</span></div>
        </div>
        <p>בהגדרות ← קודי גישה למכשירים, יוצרים קוד לכל ילד ומסמנים "מצב ילדים": שעות, אפליקציות מורשות, מכסה יומית, והאם מותר לכבות או לתזמן. במסך הבית רואים <b className="text-text">זמן מסך</b> לפי יום ולפי אפליקציה.</p>
      </Step>
    </div>
  )
}

function Faq() {
  const items: [string, ReactNode][] = [
    ['כתוב "אין חיבור לשרת השלט"', 'המחשב שמריץ את המערכת כבוי או שאין לו אינטרנט. אפשר לעבור לזמן מה למצב הדגמה כדי לראות איך זה נראה, אבל שום דבר לא נשלח למכשירים.'],
    ['הטלוויזיה אדומה במפה', 'כנראה כבויה. אם דלוקה, מחכים כדקה וחצי: המערכת מחפשת אותה לבד ומעדכנת את הכתובת אם הראוטר שינה אותה.'],
    ['הלחיצות "לא עושות כלום"', 'בראש עמוד הממיר או הטלוויזיה לוחצים "בדיקת חיבור". ירוק: המכשיר מגיב ואז בודקים שהוא על האפליקציה הנכונה. אדום: החיבור אופס, מנסים שוב.'],
    ['כתוב "מחוץ לשעות המותרות"', 'זה מצב ילדים. לוחצים "בקש עוד זמן".'],
    ['עוצמה לא משתנה בטלוויזיה', 'אם הקול יוצא למערכת סאונד חיצונית (אופטי), הטלוויזיה לא שולטת בו. שולטים בעוצמה במערכת הסאונד או משנים בטלוויזיה את יציאת הקול.'],
    ['ספוטיפיי נפתחת לדף התקנה', 'האפליקציה לא מותקנת במכשיר הזה. מתקינים אותה פעם אחת עם השלט הרגיל.'],
    ['המיקרופון לא עובד', 'דורש גישה מאובטחת (HTTPS) והרשאה בדפדפן. תמיד אפשר להקליד את הפקודה.'],
    ['איבדתי את הטלפון', 'מבקשים מהמנהל לבטל את הקוד של הטלפון הזה. שאר המשפחה לא מושפעת.'],
  ]
  return (
    <div className="flex flex-col gap-2">
      {items.map(([q, a]) => (
        <details key={q} className="group rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-semibold">
            {q}<ChevronDown aria-hidden className="shrink-0 transition-transform group-open:rotate-180" size={18} />
          </summary>
          <p className="mt-2 text-sm text-muted">{a}</p>
        </details>
      ))}
    </div>
  )
}

const TABS = [
  { id: 'start', label: 'התחלה', node: <Start /> },
  { id: 'remote', label: 'שלט', node: <RemoteHelp /> },
  { id: 'apps', label: 'אפליקציות וחיפוש', node: <AppsHelp /> },
  { id: 'voice', label: 'קול', node: <VoiceHelp /> },
  { id: 'kids', label: 'ילדים', node: <KidsHelp /> },
  { id: 'faq', label: 'תקלות', node: <Faq /> },
] as const

export default function Help() {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('start')
  const current = TABS.find((t) => t.id === tab)!
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-extrabold">מדריך</h1>
        <p className="text-muted">הכול על שלט אחד לכל הבית, בכמה דקות.</p>
      </div>

      <div role="tablist" aria-label="נושאי המדריך" className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.id} role="tab" type="button" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`panel-${t.id}`} onClick={() => setTab(t.id)}
            className={`chip !text-sm !px-4 !py-2 ${tab === t.id ? 'ok' : ''}`}>{t.label}</button>
        ))}
      </div>

      <Card>
        <div role="tabpanel" id={`panel-${current.id}`} aria-labelledby={`tab-${current.id}`}>{current.node}</div>
      </Card>

      <p className="flex items-center gap-2 text-xs text-muted"><Wifi size={14} aria-hidden /> המדריך עצמו עובד גם במצב הדגמה ובלי חיבור.</p>
    </div>
  )
}
