import { useEffect, useRef } from 'preact/hooks';

/**
 * Move focus to the screen's heading when it opens, so screen readers announce
 * the new screen after a route change. Give the element tabIndex={-1}.
 */
export function useFocusOnMount<T extends HTMLElement>(enabled = true) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (enabled) ref.current?.focus({ preventScroll: false });
  }, [enabled]);
  return ref;
}
