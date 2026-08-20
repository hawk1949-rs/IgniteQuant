import { useEffect, useState } from 'react'

/** Match a CSS media query; SSR-safe default is false (desktop-first). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false
    }
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setMatches(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** Tailwind `sm` breakpoint is 640px — below that is phone portrait. */
export function useIsPhone(): boolean {
  return useMediaQuery('(max-width: 639px)')
}

/** Below Tailwind `xl` (1280px) — stack dual charts / use tabs. */
export function useIsBelowXl(): boolean {
  return useMediaQuery('(max-width: 1279px)')
}
