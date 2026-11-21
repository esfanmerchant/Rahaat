/** The Rahat mark: a shelter roof over a person. Same geometry as public/favicon.svg. */
export function RahatMark({ size = 80, class: className = '' }: { size?: number; class?: string }) {
  return (
    <svg viewBox="0 0 512 512" width={size} height={size} aria-hidden="true" focusable="false" class={`shrink-0 ${className}`}>
      <rect width="512" height="512" rx="96" fill="#0d5c3d" />
      <path d="M120 250L256 130l136 120" fill="none" stroke="#ffffff" stroke-width="44" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="256" cy="262" r="44" fill="#ffffff" />
      <path d="M156 392a100 76 0 0 1 200 0z" fill="#ffffff" />
    </svg>
  );
}
