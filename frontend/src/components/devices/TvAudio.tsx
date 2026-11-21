import { useQuery } from '@tanstack/react-query'
import { Bluetooth, ChevronLeft, Speaker, Tv2, VolumeX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApp } from '../../app/store'
import { api } from '../../services/api'
import type { SpeakerBluetooth, SpeakerSources, TvAudio } from '../../types'

/** The speaker's Bluetooth link is the TV only when the speaker itself says so, by the connected device's name. */
const TV_NAME = /\bLG\b|webos/i

/** True only when all three agree: the TV sends sound over Bluetooth, the speaker plays from Bluetooth,
 * and the device connected to the speaker is this TV. Anything missing or unreadable means "not verified". */
export function zeppelinIsTvOutput(audio: TvAudio | null | undefined, bt: SpeakerBluetooth | undefined, src: SpeakerSources | undefined): boolean {
  if (audio?.state !== 'ready' || audio.output_kind !== 'bluetooth') return false
  const active = Array.isArray(src?.sources) ? src.sources.find((s) => s.active) : undefined
  return active?.id === 'bluetooth' && typeof bt?.connected_device === 'string' && TV_NAME.test(bt.connected_device)
}

/** Where the TV's sound goes, read from the device list (no extra requests to the TV). Read only: sends nothing. */
export function TvAudioStatus({ audio }: { audio?: TvAudio | null }) {
  const { token, mode } = useApp()
  const bluetooth = mode === 'live' && audio?.state === 'ready' && audio.output_kind === 'bluetooth'
  // the speaker is asked only while the TV says Bluetooth; same queries as the speaker page
  const bt = useQuery({ queryKey: ['speaker-bt', token], queryFn: () => api.speakerBluetooth(token), enabled: bluetooth, retry: false, refetchInterval: 15_000 })
  const src = useQuery({ queryKey: ['speaker-sources', token], queryFn: () => api.speakerSources(token), enabled: bluetooth, retry: false, refetchInterval: 15_000 })
  const verified = bluetooth && zeppelinIsTvOutput(audio, bt.data, src.data)
  const sp = useQuery({ queryKey: ['speaker', token], queryFn: () => api.speaker(token), enabled: verified, retry: false, refetchInterval: 5_000 })

  if (!audio) return null
  if (audio.state !== 'ready') {
    return (
      <p role="status" className="text-xs text-muted">
        {audio.state === 'offline' ? 'מצב הקול לא זמין: השרת לא מחובר לטלוויזיה.' : 'ממתין לנתוני קול מהטלוויזיה…'}
      </p>
    )
  }
  const Icon = audio.output_kind === 'bluetooth' ? Bluetooth : audio.output_kind === 'tv_speaker' ? Tv2 : Speaker
  const spVol = sp.data?.reachable ? sp.data.volume : null
  return (
    <div className="flex flex-col gap-2">
      <div role="status" aria-label="מצב הקול של הטלוויזיה" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="flex items-center gap-1.5">
          <Icon size={16} className="text-secondary shrink-0" aria-hidden />
          הקול יוצא ל<bdi className="font-semibold">{audio.output_label ?? 'לא ידוע'}</bdi>
        </span>
        {audio.tv_volume != null && <span className="text-muted">עוצמת טלוויזיה <b className="text-text tabular-nums">{audio.tv_volume}</b></span>}
        {audio.tv_muted && <span className="flex items-center gap-1 text-warn"><VolumeX size={14} aria-hidden /> מושתקת</span>}
      </div>

      {verified ? (
        <div className="rounded-xl border border-secondary/30 bg-secondary/5 px-3 py-2.5 flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className="flex items-center gap-1.5"><Speaker size={16} className="text-secondary" aria-hidden /> הרמקול Zeppelin מנגן את הטלוויזיה</span>
            {spVol != null && <span className="text-muted">עוצמת רמקול <b className="text-text tabular-nums">{spVol}</b></span>}
          </div>
          <p className="text-[11px] text-muted">
            הלחצנים כאן משנים את עוצמת הטלוויזיה, והיא עוברת לרמקול. הגדרות הצליל של LG (EQ, מצב צליל) לא פועלות בבלוטות'.
          </p>
          <Link to="/speaker" className="self-start flex items-center gap-1 text-sm font-semibold text-secondary hover:underline">
            עוצמה, EQ ופרופילים ברמקול <ChevronLeft size={16} aria-hidden />
          </Link>
        </div>
      ) : bluetooth && (bt.isFetched || bt.isError) && src.isFetched ? (
        <p className="text-[11px] text-muted">הקול יוצא למכשיר בלוטות' שלא זוהה כרמקול שלנו, לכן השליטה ברמקול לא מוצגת כאן.</p>
      ) : null}
    </div>
  )
}
