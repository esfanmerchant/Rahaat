import { useEffect, useState } from 'preact/hooks';

/** True while a media query matches (updates live). False where matchMedia does not exist. */
export function useMedia(query: string): boolean {
  const read = (): boolean => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const list = window.matchMedia(query);
    const onChange = (): void => setMatches(list.matches);
    onChange();
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

/** A laptop or projector: wide enough for the two-pane showcase (1024 px and up). */
export function useDesktop(): boolean {
  return useMedia('(min-width: 1024px)');
}
