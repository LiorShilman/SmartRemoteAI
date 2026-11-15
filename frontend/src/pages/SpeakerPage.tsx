import { SpeakerCard } from '../components/devices/SpeakerCard'
import { SpeakerEq } from '../components/devices/SpeakerEq'
import { SpeakerProfiles } from '../components/devices/SpeakerProfiles'
import { useBackend } from '../hooks/useDevices'
import { useApp } from '../app/store'

/** The speaker on its own screen: controls, EQ and profiles (the same cards as on the home screen). */
export default function SpeakerPage() {
  const mode = useApp((s) => s.mode)
  const backend = useBackend()
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold">רמקול</h1>
        <p className="text-muted">עוצמה, טון, תאורה, אקולייזר ופרופילים.</p>
      </div>
      {mode !== 'live' || backend !== 'online' ? (
        <p className="text-muted" role="status">הרמקול זמין רק בחיבור לשרת (לא במצב הדגמה).</p>
      ) : (
        <div className="grid gap-4 grid-cols-[minmax(0,1fr)] md:grid-cols-2">
          <SpeakerCard />
          <div className="flex flex-col gap-4 min-w-0"><SpeakerEq /><SpeakerProfiles /></div>
        </div>
      )}
    </div>
  )
}
