import type { JSX } from 'preact';

/**
 * Rahat pictograms: one hand-drawn set, 48x48 grid, 3px round strokes in
 * currentColor, no fills except small dots. Colour comes from the parent
 * (text-primary, text-danger...). Directional icons mirror in RTL.
 *
 * Use them with a word next to them where there is room; the picture carries
 * the meaning for people who cannot read, the word helps those who can.
 */
const ICONS = {
  yes: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M15.5 24.5l6 6 11-12" />
    </>
  ),
  no: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M17 17l14 14M31 17L17 31" />
    </>
  ),
  speaker: () => (
    <>
      <path d="M7 19h7l10-8v26l-10-8H7z" />
      <path d="M31 18a8.5 8.5 0 0 1 0 12M36 13a15 15 0 0 1 0 22" />
    </>
  ),
  back: () => <path d="M20 12L8 24l12 12M8 24h32" />,
  forward: () => <path d="M28 12l12 12-12 12M40 24H8" />,
  'person-help': () => (
    <>
      <circle cx="17" cy="15" r="6" />
      <path d="M5 41v-3a12 12 0 0 1 24 0v3" />
      <path d="M30 7h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-5l-5 4v-4h-2a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
      <path d="M32.5 13.5h.01M36 13.5h.01M39.5 13.5h.01" />
    </>
  ),
  document: () => (
    <>
      <path d="M12 5h16l10 10v28H12z" />
      <path d="M28 5v10h10M18 24h14M18 30h14M18 36h9" />
    </>
  ),
  payment: () => (
    <>
      <rect x="5" y="12" width="38" height="24" rx="3" />
      <circle cx="24" cy="24" r="5" />
      <path d="M10 24h3M35 24h3" />
    </>
  ),
  family: () => (
    <>
      <circle cx="11" cy="10" r="5" />
      <circle cx="37" cy="10" r="5" />
      <circle cx="24" cy="24" r="3.5" />
      <path d="M4 42V26a7 7 0 0 1 14 0v16M30 42V26a7 7 0 0 1 14 0v16M19 42v-7a5 5 0 0 1 10 0v7" />
    </>
  ),
  widow: () => (
    <>
      <circle cx="24" cy="16" r="6" />
      <path d="M14 26c0-12 4-19 10-19s10 7 10 19" />
      <path d="M9 42c0-9 6-15 15-15s15 6 15 15" />
    </>
  ),
  disability: () => (
    <>
      <circle cx="20" cy="8" r="3.5" />
      <path d="M20 14v12h10l4 11M20 19h8" />
      <path d="M14 24a10 10 0 1 0 15.8 10" />
    </>
  ),
  phone: () => (
    <>
      <rect x="14" y="4" width="20" height="40" rx="3" />
      <path d="M21 38h6" />
    </>
  ),
  warning: () => (
    <>
      <path d="M24 6L44 40H4z" />
      <path d="M24 18v10M24 34h.01" />
    </>
  ),
  retry: () => <path d="M39 24a15 15 0 1 1-4.4-10.6M35 5v9h-9" />,
  offline: () => (
    <>
      <path d="M6 19a26 26 0 0 1 36 0M12 26a17 17 0 0 1 24 0M18 33a8.5 8.5 0 0 1 12 0M24 39h.01" />
      <path d="M8 6l32 36" />
    </>
  ),
  lock: () => (
    <>
      <rect x="10" y="21" width="28" height="21" rx="3" />
      <path d="M16 21v-6a8 8 0 0 1 16 0v6M24 29v6" />
    </>
  ),
  person: () => (
    <>
      <circle cx="24" cy="15" r="8" />
      <path d="M9 42v-2a15 15 0 0 1 30 0v2" />
    </>
  ),
  delete: () => (
    <>
      <path d="M17 11h23a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H17L5 24z" />
      <path d="M23 18l12 12M35 18L23 30" />
    </>
  ),
  home: () => (
    <>
      <path d="M6 22L24 7l18 15" />
      <path d="M11 18v24h26V18M20 42V31h8v11" />
    </>
  ),
  clock: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M24 13v11l7 5" />
    </>
  ),
  camera: () => (
    <>
      <path d="M5 16a3 3 0 0 1 3-3h6l3-5h14l3 5h6a3 3 0 0 1 3 3v21a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3z" />
      <circle cx="24" cy="25" r="7" />
    </>
  ),
  microphone: () => (
    <>
      <rect x="18" y="5" width="12" height="22" rx="6" />
      <path d="M11 22a13 13 0 0 0 26 0M24 35v7M17 42h14" />
    </>
  ),
} satisfies Record<string, () => JSX.Element>;

export type PictogramName = keyof typeof ICONS;

/** Icons that point along the reading direction and so mirror in RTL. */
const DIRECTIONAL: ReadonlySet<PictogramName> = new Set<PictogramName>(['back', 'forward', 'delete']);

export const PICTOGRAM_NAMES = Object.keys(ICONS) as PictogramName[];

interface PictogramProps {
  name: PictogramName;
  /** Pixel size of the square. Citizen answers use 64 or more. */
  size?: number;
  /** Accessible name. Leave empty when a visible word sits next to the icon. */
  label?: string;
  /**
   * Set false inside an LTR island in an RTL page (the keypad, a phone number):
   * Tailwind's rtl: variant matches any element with an RTL ancestor, so the
   * nearer dir="ltr" alone does not stop the mirroring.
   */
  mirror?: boolean;
  class?: string;
}

export function Pictogram({ name, size = 48, label, mirror = true, class: className = '' }: PictogramProps) {
  const flip = mirror && DIRECTIONAL.has(name) ? 'rtl:-scale-x-100' : '';
  const a11y = label ? { role: 'img' as const, 'aria-label': label } : { 'aria-hidden': true as const };
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      stroke-width="3"
      stroke-linecap="round"
      stroke-linejoin="round"
      focusable="false"
      class={`shrink-0 ${flip} ${className}`}
      {...a11y}
    >
      {ICONS[name]()}
    </svg>
  );
}
