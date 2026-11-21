import type { ComponentChildren } from 'preact';

let sealCount = 0;

/**
 * A stamp: a ring of small text around whatever is in the middle (a code, a tick). Decorative text only
 * (aria-hidden); the middle is real content. The ring turns very slowly and the stamp lands with a pop.
 */
export function Seal({ children, size = 176, tone = 'primary' }: { children: ComponentChildren; size?: number; tone?: 'primary' | 'noor' | 'night' }) {
  sealCount += 1;
  const id = `seal-ring-${sealCount}`;
  const color = tone === 'night' ? 'text-noor' : tone === 'noor' ? 'text-noor-strong' : 'text-primary-strong';
  return (
    <div class={`relative mx-auto grid place-items-center motion-safe:animate-pop ${color}`} style={{ width: `${size}px`, height: `${size}px` }}>
      <svg viewBox="0 0 120 120" width={size} height={size} class="absolute inset-0 overflow-visible" aria-hidden="true" focusable="false">
        <circle cx="60" cy="60" r="57" fill="none" stroke="currentColor" stroke-width="2.5" />
        <circle cx="60" cy="60" r="35" fill="none" stroke="currentColor" stroke-width="1.5" />
        <g class="motion-safe:animate-spin-slow" style={{ transformOrigin: '60px 60px' }}>
          <defs>
            <path id={id} d="M60 60m-45 0a45 45 0 1 1 90 0a45 45 0 1 1-90 0" />
          </defs>
          <text lang="en" style={{ direction: 'ltr', unicodeBidi: 'isolate' }} font-size="11" font-weight="700" letter-spacing="1.5" fill="currentColor">
            <textPath href={`#${id}`} textLength="276" lengthAdjust="spacing">
              RAHAT · PROTOTYPE · RAHAT · PROTOTYPE ·
            </textPath>
          </text>
        </g>
      </svg>
      <div class="relative flex max-w-[62%] flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}
