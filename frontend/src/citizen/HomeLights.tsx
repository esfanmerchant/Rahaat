/**
 * A field of twinkling "home lights": each dot is a family. CSS only (no images); positions are fixed so the
 * sky is the same every visit. Under reduced motion the dots simply stay lit.
 */
const LIGHTS = (() => {
  let seed = 20261121;
  const next = (): number => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  return Array.from({ length: 34 }, (_, i) => ({
    x: Math.round(next() * 1000) / 10,
    y: Math.round((8 + next() * 90) * 10) / 10,
    size: 2 + Math.floor(next() * 4),
    delay: Math.round(next() * 3200),
    warm: i % 4 !== 0,
  }));
})();

export function HomeLights({ class: className = '' }: { class?: string }) {
  return (
    <div aria-hidden="true" class={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      {LIGHTS.map((l, i) => (
        <span
          key={i}
          class={`absolute rounded-full motion-safe:animate-twinkle ${l.warm ? 'bg-noor shadow-glow' : 'bg-emerald-glow shadow-glow-emerald'}`}
          style={{ insetInlineStart: `${l.x}%`, top: `${l.y}%`, width: `${l.size}px`, height: `${l.size}px`, animationDelay: `${l.delay}ms` }}
        />
      ))}
    </div>
  );
}
