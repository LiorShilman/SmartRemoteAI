import { useSyncExternalStore } from 'react'

/** Narrow screens (below Tailwind's md, where the speaker page drops to one column) get the phone layout. */
const QUERY = '(max-width: 767px)'

const subscribe = (on: () => void) => {
  const m = window.matchMedia(QUERY)
  m.addEventListener('change', on)
  return () => m.removeEventListener('change', on)
}

export function usePhone(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(QUERY).matches, () => false)
}
