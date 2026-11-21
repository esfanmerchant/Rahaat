interface SpinnerProps {
  size?: number;
  /** Accessible name; omit when a visible "please wait" text is next to it. */
  label?: string;
  class?: string;
}

/** A quarter-arc spinner in currentColor. Stops spinning under reduced motion. */
export function Spinner({ size = 24, label, class: className = '' }: SpinnerProps) {
  const a11y = label ? { role: 'img' as const, 'aria-label': label } : { 'aria-hidden': true as const };
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      stroke-width="5"
      stroke-linecap="round"
      focusable="false"
      class={`shrink-0 motion-safe:animate-spin ${className}`}
      {...a11y}
    >
      <circle cx="24" cy="24" r="18" stroke-opacity="0.25" />
      <path d="M24 6a18 18 0 0 1 18 18" />
    </svg>
  );
}
