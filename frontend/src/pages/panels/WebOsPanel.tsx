import { useState } from 'react'
import { Home, Power, Tv2, Undo2, Volume1, Volume2, VolumeX } from 'lucide-react'
import { Card, CapChip, Key, SectionTitle } from '../../components/ui/Primitives'
import { DPad } from '../../components/remote/Controls'
import { AppLauncher } from '../../components/remote/AppLauncher'
import { Touchpad } from '../../components/remote/Touchpad'
import { useRemote } from '../../hooks/useRemote'
import type { Device } from '../../types'

/** Controls for an LG webOS device (real pointer, inputs, apps, power off). */
export default function WebOsPanel({ device: dev }: { device: Device }) {
  const { device, press, can, blocked } = useRemote(dev)
  const [confirmOff, setConfirmOff] = useState(false)
  const key = (k: string, label: string) => () => press({ target: 'lg', action: 'key_press', params: { key: k } }, label)

  return (
    <div className="flex flex-col gap-5">
      {blocked && <div role="status" className="glass px-4 py-3 text-sm text-warn">{blocked}</div>}
      {!device && null}

      <div className="grid gap-5 grid-cols-[minmax(0,1fr)] lg:grid-cols-2">
        <div className="flex flex-col gap-5">
        <Card className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3">
            <Key label="בית" className="h-14" disabled={!can('nav')} onClick={key('HOME', 'בית')}><Home /></Key>
            <Key label="חזור" className="h-14" disabled={!can('nav')} onClick={key('BACK', 'חזור')}><Undo2 /></Key>
          </div>
          <DPad target="lg" press={press} disabled={!can('nav')} />
        </Card>

        <Card>
          <SectionTitle hint="פותחים תפריטים בטלוויזיה. התפריט המהיר מכיל תמונה, צליל וחיבורים.">תפריטים</SectionTitle>
          <div className="grid grid-cols-2 gap-3">
            <Key label="תפריט" className="h-12 text-sm" disabled={!can('nav')} onClick={key('MENU', 'תפריט')}>תפריט</Key>
            <Key label="תפריט מהיר" className="h-12 text-sm" disabled={!can('nav')} onClick={key('QMENU', 'תפריט מהיר')}>תפריט מהיר</Key>
            <Key label="מידע" className="h-12 text-sm" disabled={!can('nav')} onClick={key('INFO', 'מידע')}>מידע</Key>
            <Key label="מדריך שידורים" className="h-12 text-sm" disabled={!can('nav')} onClick={key('GUIDE', 'מדריך')}>מדריך</Key>
            <Key label="יציאה" className="h-12 text-sm" disabled={!can('nav')} onClick={key('EXIT', 'יציאה')}>יציאה</Key>
            <Key label="בחירת כניסה" className="h-12 text-sm" disabled={!can('nav')} onClick={key('INPUT_HUB', 'כניסות')}>כניסות</Key>
          </div>
        </Card>

        <Card className="lg:flex-1 flex flex-col">
          <SectionTitle hint="מצביע אמיתי על מסך הטלוויזיה.">עכבר</SectionTitle>
          <div className="flex-1 flex flex-col justify-end"><Touchpad device={device!} disabled={!can('nav')} /></div>
        </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card>
            <SectionTitle>עוצמה</SectionTitle>
            <div className="grid grid-cols-3 gap-3">
              <Key label="הנמך עוצמה" className="h-16" disabled={!can('volume')}
                onClick={() => press({ target: 'lg', action: 'volume_down' }, 'עוצמה −')}><Volume1 /></Key>
              <Key label="השתק" className="h-16" disabled={!can('mute')}
                onClick={() => press({ target: 'lg', action: 'mute' }, 'השתקה')}><VolumeX /></Key>
              <Key label="הגבר עוצמה" className="h-16" disabled={!can('volume')}
                onClick={() => press({ target: 'lg', action: 'volume_up' }, 'עוצמה +')}><Volume2 /></Key>
            </div>
          </Card>

          <Card>
            <SectionTitle hint="רשימה מזוהה בלבד — המקורות בפועל ייקבעו מול הטלוויזיה.">כניסות</SectionTitle>
            <div className="grid grid-cols-4 gap-3 ltr">
              {[1, 2, 3, 4].map((n) => (
                <Key key={n} label={`HDMI ${n}`} className="h-14 text-sm font-bold" disabled={!can('inputs')}
                  onClick={() => press({ target: 'lg', action: 'set_input', params: { input: `HDMI_${n}` } }, `HDMI ${n}`)}>
                  <Tv2 size={16} /> {n}
                </Key>
              ))}
            </div>
          </Card>

          <Card>
            <SectionTitle>אפליקציות</SectionTitle>
            <AppLauncher target="lg" press={press} disabled={!can('apps')} />
          </Card>

          <Card className="lg:flex-1">
            <SectionTitle>הפעלה</SectionTitle>
            <div className="flex flex-col gap-3">
              {!confirmOff ? (
                <Key label="כבה טלוויזיה" variant="danger" className="h-14 w-full" disabled={!can('power_off')} onClick={() => setConfirmOff(true)}>
                  <Power /> כיבוי
                </Key>
              ) : (
                <div className="flex gap-3">
                  <Key label="אשר כיבוי" variant="danger" className="h-14 flex-1 font-bold"
                    onClick={() => { press({ target: 'lg', action: 'power_off' }, 'כיבוי'); setConfirmOff(false) }}>
                    לכבות עכשיו?
                  </Key>
                  <Key label="ביטול" className="h-14 px-5" onClick={() => setConfirmOff(false)}>ביטול</Key>
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <Key label="הפעל טלוויזיה" className="h-14 flex-1" disabled={device?.capabilities.wol !== 'supported'}
                  onClick={() => press({ target: 'lg', action: 'power_on' }, 'הפעלה')}>
                  <Power /> הפעלה
                </Key>
                <CapChip state={device?.capabilities.wol} />
              </div>
              <p className="text-xs text-muted">
                הפעלה מרחוק (Wake-on-LAN) זמינה רק אחרי שהתגלתה כתובת MAC והאפשרות נבדקה בפועל. עד אז היא כבויה.
              </p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
