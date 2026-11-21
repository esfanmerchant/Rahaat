import { useEffect, useRef, useState } from 'preact/hooks';

const reduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** A number that counts up (or down) to its target, so a live refresh is visible. Shows the value at once for reduced motion. */
export function useCountUp(target: number, ms = 1100): number {
  const [shown, setShown] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    if (reduced() || from.current === target) {
      from.current = target;
      setShown(target);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - k, 3);
      const value = Math.round(origin + (target - origin) * eased);
      from.current = value;
      setShown(value);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return shown;
}

export function Counter({ value, class: className = '' }: { value: number; class?: string }) {
  const shown = useCountUp(value);
  return <span class={`tabular-nums ${className}`}>{shown.toLocaleString('en-US')}</span>;
}
