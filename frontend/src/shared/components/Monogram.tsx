/**
 * A geometric avatar: the person's initials inside a small eight-point star, coloured from a hash of the name
 * (always one of the palette's dyes with white text of AAA or near contrast). Never a photo, never a real face.
 */
const DYES = ['#24409e', '#a3203a', '#0b6a46', '#6a4100', '#2a3570'] as const;

function hash(text: string): number {
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) h = (h * 33) ^ text.charCodeAt(i);
  return Math.abs(h);
}

export function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => Array.from(word)[0] ?? '')
    .join('');
}

export function Monogram({ name, size = 56, class: className = '' }: { name: string; size?: number; class?: string }) {
  const fill = DYES[hash(name) % DYES.length];
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} class={`shrink-0 ${className}`} aria-hidden="true" focusable="false">
      <rect x="15" y="15" width="70" height="70" rx="6" fill={fill} />
      <rect x="15" y="15" width="70" height="70" rx="6" fill={fill} transform="rotate(45 50 50)" />
      <circle cx="50" cy="50" r="40" fill="none" stroke="#ffd36e" stroke-opacity=".55" stroke-width="2" />
      <text x="50" y="52" text-anchor="middle" dominant-baseline="central" font-size="30" font-weight="700" fill="#fff" dir="auto">
        {initialsOf(name)}
      </text>
    </svg>
  );
}
