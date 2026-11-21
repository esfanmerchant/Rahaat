/**
 * The Rahat emblem (Noor visual language): the eight-point star of the ajrak block, a lamp at its centre and
 * eight homes around it. The star is two squares; with `animate` they draw themselves, the homes light up one
 * after another and the lamp glows. Pure SVG and CSS: no script runs for the animation.
 */
const HOMES = Array.from({ length: 8 }, (_, k) => {
  const angle = ((22.5 + k * 45) * Math.PI) / 180;
  return { x: 50 + 44 * Math.cos(angle), y: 50 + 44 * Math.sin(angle), k };
});

export type EmblemTone = 'paper' | 'night' | 'mono';

const TONES: Record<EmblemTone, { star: string; lamp: string; homes: string }> = {
  paper: { star: '#24409e', lamp: '#f2a51e', homes: '#0b6a46' },
  night: { star: '#ffd36e', lamp: '#ffd36e', homes: '#4ee6a6' },
  mono: { star: 'currentColor', lamp: 'currentColor', homes: 'currentColor' },
};

export function Emblem({
  size = 80,
  tone = 'paper',
  animate = false,
  class: className = '',
  title,
}: {
  size?: number;
  tone?: EmblemTone;
  animate?: boolean;
  class?: string;
  title?: string;
}) {
  const c = TONES[tone];
  const draw = animate ? 'rh-draw' : undefined;
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      class={`shrink-0 overflow-visible ${className}`}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : 'true'}
      focusable="false"
    >
      <g fill="none" stroke={c.star} stroke-width="4.5" stroke-linejoin="round">
        <path d="M22 22h56v56H22z" pathLength={100} class={draw} />
        <path d="M50 10.4 89.6 50 50 89.6 10.4 50z" pathLength={100} class={draw} style={animate ? { '--delay': '220ms' } : undefined} />
      </g>
      <circle cx="50" cy="50" r="15" fill="none" stroke={c.star} stroke-width="2" opacity="0.5" />
      <circle
        cx="50"
        cy="50"
        r="8.5"
        fill={c.lamp}
        class={animate ? 'motion-safe:animate-pop' : undefined}
        style={animate ? { animationDelay: '900ms', transformOrigin: '50px 50px', transformBox: 'fill-box' } : undefined}
      />
      {HOMES.map((h) => (
        <circle
          key={h.k}
          cx={h.x}
          cy={h.y}
          r="3.4"
          fill={c.homes}
          class={animate ? 'motion-safe:animate-pop' : undefined}
          style={animate ? { animationDelay: `${1000 + h.k * 90}ms`, transformOrigin: 'center', transformBox: 'fill-box' } : undefined}
        />
      ))}
    </svg>
  );
}
