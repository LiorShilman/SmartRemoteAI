import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, FastForward, Home, Menu, Pause, Rewind, Undo2, Volume1, Volume2, VolumeX } from 'lucide-react'
import { Card, CapChip, Key, SectionTitle } from '../../components/ui/Primitives'
import { DPad, Favorites, Keypad } from '../../components/remote/Controls'
import { AppLauncher } from '../../components/remote/AppLauncher'
import { Touchpad } from '../../components/remote/Touchpad'
import { useVolumeDevice } from '../../hooks/useDevices'
import { ROLE_LABEL } from '../../services/roles'
import type { Device } from '../../types'
import { useRemote } from '../../hooks/useRemote'
import { ApiError, api } from '../../services/api'
import { CHANNEL_KEYS, useApp } from '../../app/store'

/** Controls for an Android TV device. As a box it also has channels/keypad; as a TV it keeps nav, media, volume and apps. */
export default function AndroidPanel({ device: dev }: { device: Device }) {
  const { device, press, can, blocked } = useRemote(dev)
  const isBox = dev.role === 'box'
  // A box usually has no volume of its own: use the device the user picked for volume (default: the TV).
  const preferred = useVolumeDevice()
  const volDev = isBox ? (preferred ?? dev) : dev
  const { channelStepMode, token, toast } = useApp()
  const qc = useQueryClient()
  const tracked = channelStepMode === 'tracked'
  const [chUp, chDown] = tracked ? ['', ''] : CHANNEL_KEYS[channelStepMode]
  const [setCh, setSetCh] = useState('')
  const [showPad, setShowPad] = useState(false)
  const vol = ROLE_LABEL[volDev.role]
  const volCmd = (action: 'volume_up' | 'volume_down' | 'mute', label: string) => () =>
    press({ target: volDev.kind, deviceId: volDev.id, action }, `${label} (${vol})`)
  const key = (k: string, label: string) => () => press({ target: dev.kind, action: 'key_press', params: { key: k } }, label)

  return (
    <div className="flex flex-col gap-5">
      {blocked && <div role="status" className="glass px-4 py-3 text-sm text-warn">{blocked}</div>}

      <div className="grid gap-5 grid-cols-[minmax(0,1fr)] lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <Card className="flex flex-col gap-6">
            <div className="grid grid-cols-3 gap-3">
              <Key label="בית" className="h-14" disabled={!can('nav')} onClick={key('HOME', 'בית')}><Home /></Key>
              <Key label="תפריט" className="h-14" disabled={!can('nav')} onClick={key('MENU', 'תפריט')}><Menu /></Key>
              <Key label="חזור" className="h-14" disabled={!can('nav')} onClick={key('BACK', 'חזור')}><Undo2 /></Key>
            </div>
            <DPad target={dev.kind} press={press} disabled={!can('nav')} />
            <div className="grid grid-cols-3 gap-3">
              <Key label="הגדרות" className="h-12 text-sm" disabled={!can('nav')} onClick={key('SETTINGS', 'הגדרות')}>הגדרות</Key>
              <Key label="מדריך שידורים" className="h-12 text-sm" disabled={!can('nav')} onClick={key('GUIDE', 'מדריך')}>מדריך</Key>
              <Key label="מידע" className="h-12 text-sm" disabled={!can('nav')} onClick={key('INFO', 'מידע')}>מידע</Key>
            </div>
            <div className="grid grid-cols-3 gap-3 ltr">
              <Key label="הרצה אחורה" className="h-14" disabled={!can('media')} onClick={key('MEDIA_REWIND', 'הרצה אחורה')}><Rewind /></Key>
              <Key label="נגן או השהה" className="h-14" disabled={!can('media')} onClick={key('MEDIA_PLAY_PAUSE', 'נגן / השהה')}><Pause /></Key>
              <Key label="הרצה קדימה" className="h-14" disabled={!can('media')} onClick={key('MEDIA_FAST_FORWARD', 'הרצה קדימה')}><FastForward /></Key>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted justify-center">
              מדיה: <CapChip state={device?.capabilities.media} />
            </div>
          </Card>

          <Card className={isBox ? '' : 'lg:flex-1'}>
            <SectionTitle hint="נפתחות במכשיר לפי שם האפליקציה. אם היא לא מותקנת, ייפתח דף ההתקנה שלה.">
              אפליקציות <CapChip state={device?.capabilities.apps} />
            </SectionTitle>
            <AppLauncher target={dev.kind} press={press} disabled={!can('apps')} />
          </Card>

          {isBox && <Card className="lg:flex-1">
            <SectionTitle>ערוצים מועדפים</SectionTitle>
            <Favorites target={dev.kind} press={press} disabled={!can('digits')} />
          </Card>}
        </div>

        <div className="flex flex-col gap-5">
          <Card className={isBox ? '' : 'lg:flex-1'}>
            <SectionTitle hint={`עוצמת הקול נשלחת אל: ${vol}${volDev.id === dev.id ? '' : ' (ניתן לשנות בהגדרות)'}.`}>{isBox ? 'עוצמה וערוצים' : 'עוצמה'}</SectionTitle>
            <div className={`grid gap-4 ${isBox ? 'grid-cols-2' : 'grid-cols-1'}`}>
              <div className="flex flex-col gap-3 items-stretch">
                <span className="text-xs text-muted text-center">עוצמה · {vol}</span>
                <Key label="הגבר עוצמה" className="h-14" disabled={volDev.id === dev.id && blocked !== null} onClick={volCmd('volume_up', 'עוצמה +')}><Volume2 /></Key>
                <Key label="הנמך עוצמה" className="h-14" disabled={volDev.id === dev.id && blocked !== null} onClick={volCmd('volume_down', 'עוצמה −')}><Volume1 /></Key>
                <Key label="השתק" className="h-14" disabled={volDev.id === dev.id && blocked !== null} onClick={volCmd('mute', 'השתקה')}><VolumeX /></Key>
              </div>
              {isBox && (<div className="flex flex-col gap-3 items-stretch">
                <span className="text-xs text-muted text-center">ערוץ</span>
                <Key label="ערוץ הבא" className="h-14" disabled={!can(tracked ? 'digits' : 'channel_step')} onClick={tracked ? () => press({ target: dev.kind, action: 'channel_step', params: { delta: 1 } }, 'ערוץ +') : key(chUp, 'ערוץ +')}><ChevronUp /></Key>
                <Key label="ערוץ קודם" className="h-14" disabled={!can(tracked ? 'digits' : 'channel_step')} onClick={tracked ? () => press({ target: dev.kind, action: 'channel_step', params: { delta: -1 } }, 'ערוץ −') : key(chDown, 'ערוץ −')}><ChevronDown /></Key>
                <Key label="ערוץ אחרון" className="h-14 text-sm" disabled={!can(tracked ? 'digits' : 'channel_step')} onClick={tracked ? () => press({ target: dev.kind, action: 'channel_last' }, 'ערוץ אחרון') : key('LAST_CHANNEL', 'ערוץ אחרון')}>אחרון</Key>
              </div>)}
            </div>
          </Card>

          {isBox && <Card className="lg:flex-1">
            <SectionTitle hint="מעבר ישיר לפי ספרות. סטטוס התמיכה נקבע רק אחרי בדיקה בפועל (הגדרות).">
              מספר ערוץ <CapChip state={device?.capabilities.digits} />
            </SectionTitle>
            {tracked && (
              <div className="mb-3 rounded-2xl border border-white/10 p-3 flex flex-col gap-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted">ערוץ נוכחי (לפי מה ששלחת מהאתר)</span>
                  <b className="text-lg ltr">{device?.channel ?? '—'}</b>
                </div>
                {device?.previous_channel && <div className="text-xs text-muted">ערוץ קודם: <bdi>{device.previous_channel}</bdi></div>}
                <form className="flex gap-2" onSubmit={async (e) => {
                  e.preventDefault()
                  if (!device || !/^\d{1,4}$/.test(setCh)) return
                  try { await api.setChannel(token, device.id, setCh); setSetCh(''); void qc.invalidateQueries({ queryKey: ['devices'] }); toast('info', `הערוץ הנוכחי נקבע ל-${Number(setCh)} (לא נשלח כלום לממיר)`) }
                  catch (err) { toast('error', err instanceof ApiError ? err.message : 'העדכון נכשל.') }
                }}>
                  <input className="input ltr flex-1" inputMode="numeric" placeholder="באיזה ערוץ הוא עכשיו?" aria-label="קביעת הערוץ הנוכחי"
                    value={setCh} onChange={(e) => setSetCh(e.target.value.replace(/\D/g, '').slice(0, 4))} />
                  <Key label="קבע ערוץ נוכחי" className="px-4 h-12 text-sm" type="submit" disabled={!setCh || !device}>קבע</Key>
                </form>
                <p className="text-xs text-muted">הממיר לא מדווח על הערוץ שלו. אחרי שימוש בשלט הפיזי, קבע כאן את הערוץ כדי שעליה וירידה יתחילו ממנו.</p>
              </div>
            )}
            <Keypad target={dev.kind} press={press} disabled={!can('digits')} />
          </Card>}


        </div>
      </div>

      {/* Last on purpose: an emulation (arrow presses), not a real mouse, so it stays out of the way until wanted. */}
      <Card>
        <button type="button" aria-expanded={showPad} onClick={() => setShowPad((v) => !v)}
          className="w-full flex items-center justify-between gap-3 text-start min-h-11">
          <span>
            <span className="block text-lg font-bold">משטח החלקה</span>
            <span className="block text-sm text-muted">מדמה עכבר בלחיצות על חצים (Android TV לא תומך בעכבר אמיתי)</span>
          </span>
          <ChevronDown aria-hidden className={`shrink-0 transition-transform ${showPad ? 'rotate-180' : ''}`} />
        </button>
        {showPad && <div className="mt-4"><Touchpad device={dev} disabled={!can('nav')} /></div>}
      </Card>
    </div>
  )
}
