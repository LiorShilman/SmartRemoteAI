import { useEffect, useState } from 'react'
import type { SpeakerOp, SpeakerState } from '../types'
import { fetchSpeech } from './api'

/** Spoken replies through the browser's own speech synthesis. Hebrew voice only: an English voice reading Hebrew
 * is gibberish, so without one nothing is spoken. Speaking happens only after a user's own press ("בצע"). */
const synth = (): SpeechSynthesis | undefined => (typeof window !== 'undefined' ? window.speechSynthesis : undefined)

const hebrewVoice = (): SpeechSynthesisVoice | undefined =>
  synth()?.getVoices().filter((v) => /^he|^iw/i.test(v.lang)).sort((a, b) => Number(b.localService) - Number(a.localService))[0]

export function useHebrewVoice(): { supported: boolean; voice: SpeechSynthesisVoice | undefined } {
  const s = synth()
  const [voice, setVoice] = useState(hebrewVoice)
  useEffect(() => {
    if (!s) return
    const on = () => setVoice(hebrewVoice())
    on()
    s.addEventListener('voiceschanged', on) // voices load asynchronously
    return () => s.removeEventListener('voiceschanged', on)
  }, [s])
  return { supported: !!s, voice }
}

export function speak(text: string, voice: SpeechSynthesisVoice | undefined): boolean {
  const s = synth()
  if (!s || !voice || !text.trim()) return false
  s.cancel() // a newer reply replaces one still speaking
  const u = new SpeechSynthesisUtterance(text)
  u.voice = voice
  u.lang = voice.lang
  u.rate = 1.05
  s.speak(u)
  return true
}

/** True while a spoken reply is playing (server audio or the browser voice). */
export function isSpeaking(): boolean {
  return (!!audio && !audio.paused && !audio.ended && audio.src !== SILENT) || !!synth()?.speaking
}

/** Stop any reply now (the user pressed the microphone: they want to talk, not listen). */
export function stopSpeaking(): void {
  if (audio && !audio.paused) audio.pause()
  synth()?.cancel()
}

// ---- server voice: the same Hebrew neural voice in every browser and phone (the server makes the MP3)
let audio: HTMLAudioElement | null = null
const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

/** Call synchronously inside the user's press: lets strict browsers (iOS Safari) play the reply a moment later. */
export function unlockAudio(): void {
  audio ??= new Audio()
  audio.src = SILENT
  void audio.play().catch(() => {})
}

/** Plays the server's spoken reply. False if the server or the browser refused (the caller may fall back). */
export async function speakServer(token: string, text: string): Promise<boolean> {
  if (!text.trim()) return false
  try {
    const blob = await fetchSpeech(token, text)
    audio ??= new Audio()
    const url = URL.createObjectURL(blob)
    audio.onended = () => URL.revokeObjectURL(url)
    audio.src = url
    await audio.play()
    return true
  } catch {
    return false
  }
}

const num = (n: number) => (n < 0 ? `מינוס ${-n}` : `${n}`)

/** What the speaker itself reported after the step (the read-back), in a short spoken sentence. */
export function speakerReply(op: SpeakerOp, params: Record<string, unknown>, st: SpeakerState, label: string): string {
  switch (op) {
    case 'speaker_volume': return st.volume != null ? `הרמקול על ${st.volume}` : 'העוצמה ברמקול שונתה'
    case 'speaker_mute': return st.mute ? 'הרמקול מושתק' : 'ההשתקה ברמקול בוטלה'
    case 'speaker_bass': return st.bass != null ? `באס ${num(st.bass)}` : 'הבאס שונה'
    case 'speaker_treble': return st.treble != null ? `גבוהים ${num(st.treble)}` : 'הגבוהים שונו'
    case 'speaker_light': return st.light ? 'התאורה דולקת' : 'התאורה כבויה'
    case 'speaker_brightness': return st.brightness != null ? `בהירות ${st.brightness}` : 'הבהירות שונתה'
    case 'speaker_color': return `התאורה ב${String(params.color ?? '')}`
    case 'speaker_cycle': return params.enabled ? 'החלפת הצבעים הופעלה' : 'החלפת הצבעים נעצרה'
    case 'speaker_profile': return `הפרופיל ${label.replace(/^רמקול: טעינת פרופיל\s*/, '')} נטען`
  }
}

/** "טלוויזיה: הגברת עוצמה" -> "נשלח לטלוויזיה: הגברת עוצמה". "Sent" only: a device never confirms it reacted. */
export function sentReply(label: string, simulated: boolean): string {
  const m = label.replace(/\s*\(ניסיוני\)/, '').match(/^([^:]+):\s*(.+)$/)
  const what = m ? `ל${m[1]}: ${m[2]}` : label
  return `${simulated ? 'בהדגמה, נשלח' : 'נשלח'} ${what}`
}
