import type { ComponentChildren } from 'preact';
import '../pages.css';

/**
 * Small building blocks shared by the redesigned Case review, Audit and Impact pages:
 * a card with a short title, and an info button that holds the long explanation so the page itself stays quiet.
 */

/** A small "i" button. The explanation opens in a popover (native details, so keyboard and screen readers work). */
export function Info({ label = 'More', children }: { label?: string; children: ComponentChildren }) {
  return (
    <details
      class="pg-info"
      onKeyDown={(e) => {
        if (e.key === 'Escape') (e.currentTarget as HTMLDetailsElement).open = false;
      }}
    >
      <summary aria-label={label} title={label}>
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <circle cx="8" cy="8" r="6.4" />
          <path d="M8 7.2v4M8 4.8v.1" />
        </svg>
      </summary>
      <div class="pg-pop">{children}</div>
    </details>
  );
}

/** A card: a title of at most three words, an optional aside (chips, info button), and a body. `i` staggers the entrance. */
export function Card({
  title,
  aside,
  i = 0,
  lit,
  class: cls = '',
  children,
  id,
}: {
  title?: string;
  aside?: ComponentChildren;
  i?: number;
  lit?: boolean;
  class?: string;
  children?: ComponentChildren;
  id?: string;
}) {
  return (
    <section class={`pg-card pg-rise ${lit ? 'pg-lit' : ''} ${cls}`} style={{ '--i': i }} aria-labelledby={title ? id : undefined}>
      {title || aside ? (
        <header class="pg-card-head">
          {title ? <h2 id={id}>{title}</h2> : <span />}
          {aside ? <span class="pg-aside">{aside}</span> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function Check({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 6.5 5 9.5 10.5 3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  );
}
