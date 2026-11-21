import { useEffect, useRef, useState } from 'preact/hooks';
import { prefersReducedMotion } from './theme';

/** A number that counts up from where it was to where it is now. Reduced motion shows the value at once. */
export function useCountUp(target: number, ms = 800): number {
  const [shown, setShown] = useState(prefersReducedMotion() ? target : 0);
  const from = useRef(shown);
  useEffect(() => {
    if (prefersReducedMotion() || from.current === target) {
      from.current = target;
      setShown(target);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      const value = origin + (target - origin) * eased;
      from.current = value;
      setShown(value);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return shown;
}

export function CountUp({ value, ms, format }: { value: number; ms?: number; format?: (n: number) => string }) {
  const v = useCountUp(value, ms);
  const n = Math.round(v);
  return <span class="rh-num">{format ? format(n) : n.toLocaleString('en-US')}</span>;
}

/** Priority as a small heat bar. The API's priority is 0 for most urgent; higher is calmer. */
export function HeatBar({ priority }: { priority: number }) {
  const level = priority <= 10 ? 0 : priority <= 30 ? 1 : priority <= 50 ? 2 : priority <= 75 ? 3 : 4;
  const fill = [100, 80, 60, 40, 20][level] as number;
  return (
    <span class="inline-flex items-center gap-2" title={`Priority ${priority} (0 is the most urgent)`}>
      <span class="st-heat" role="img" aria-label={`priority ${priority}, ${['critical', 'high', 'medium', 'low', 'lowest'][level]}`}>
        <i class={`st-h${level}`} style={{ width: `${fill}%` }} />
      </span>
      <span class="rh-num w-7 text-end font-mono text-xs">{priority}</span>
    </span>
  );
}

/** Age warms with time: calm at first, saffron, orange, then madder once it has waited a day. */
export function AgeChip({ minutes, text }: { minutes: number; text: string }) {
  const level = minutes < 60 ? 0 : minutes < 360 ? 1 : minutes < 1440 ? 2 : 3;
  return (
    <span class={`st-chip st-age-${level} rh-num font-mono`} title={`Open for ${text}`}>
      {text}
    </span>
  );
}
