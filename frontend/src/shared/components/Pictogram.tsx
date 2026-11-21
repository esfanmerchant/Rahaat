import type { JSX } from 'preact';

/** Shared outlines: the message bubble (tail at the start side) and the shield. */
const BUBBLE = 'M8 8h32a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H21l-9 7v-7H8a3 3 0 0 1-3-3V11a3 3 0 0 1 3-3z';
const SHIELD = 'M24 5l15 6v11c0 10-6.5 17-15 21C15.5 39 9 32 9 22V11z';

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
  /** "I do not know": a question mark in a circle. */
  unknown: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M18.5 19a5.5 5.5 0 1 1 8.2 4.8c-1.9 1-2.7 2.3-2.7 4.2v.5M24 34.5h.01" />
    </>
  ),
  plus: () => <path d="M24 9v30M9 24h30" />,
  minus: () => <path d="M9 24h30" />,
  /** The Rahat card: a photo and lines of text. */
  card: () => (
    <>
      <rect x="4" y="10" width="40" height="28" rx="3" />
      <circle cx="15" cy="21" r="4" />
      <path d="M9 32a6 6 0 0 1 12 0M26 18h12M26 24h12M26 30h8" />
    </>
  ),
  edit: () => (
    <>
      <path d="M31 8l9 9-22 22H9v-9z" />
      <path d="M26 13l9 9" />
    </>
  ),
  /** A text message: a speech bubble. The variants say what we think of it. */
  message: () => <path d={BUBBLE} />,
  'msg-scam': () => (
    <>
      <path d={BUBBLE} />
      <path d="M18.5 15.5l11 11M29.5 15.5l-11 11" />
    </>
  ),
  'msg-warn': () => (
    <>
      <path d={BUBBLE} />
      <path d="M24 14v8.5M24 28h.01" />
    </>
  ),
  'msg-unsure': () => (
    <>
      <path d={BUBBLE} />
      <path d="M19.5 17a4.5 4.5 0 1 1 6.7 3.9c-1.4.8-2.2 1.9-2.2 3.4M24 28.5h.01" />
    </>
  ),
  'msg-ok': () => (
    <>
      <path d={BUBBLE} />
      <path d="M17 21.5l5 5 9-10" />
    </>
  ),
  /** Checked by us: a shield with a tick (a real message, really sent by Rahat). */
  'shield-ok': () => (
    <>
      <path d={SHIELD} />
      <path d="M17 23.5l5 5 9-10" />
    </>
  ),
  /** The scam checker: a shield with a question ("is this safe?"). */
  shield: () => (
    <>
      <path d={SHIELD} />
      <path d="M20 19a4.2 4.2 0 1 1 6.3 3.6c-1.3.8-2.3 1.8-2.3 3.4M24 31.5h.01" />
    </>
  ),
  link: () => <path d="M20 28l8-8M17 21l-4 4a6 6 0 0 0 8.5 8.5l4-4M31 27l4-4a6 6 0 0 0-8.5-8.5l-4 4" />,
  /** Paste: a clipboard. */
  paste: () => (
    <>
      <path d="M16 9h-3a3 3 0 0 0-3 3v28a3 3 0 0 0 3 3h22a3 3 0 0 0 3-3V12a3 3 0 0 0-3-3h-3" />
      <path d="M18 5h12v7H18zM17 22h14M17 28h14M17 34h9" />
    </>
  ),
  /** Share less: a minus in a circle. */
  less: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M15 24h18" />
    </>
  ),
  /** Waiting, stopped for now: two bars in a circle. */
  pause: () => (
    <>
      <circle cx="24" cy="24" r="19" />
      <path d="M20 17v14M28 17v14" />
    </>
  ),
  /** Saved on this phone: a phone with a tick on its screen. */
  'phone-saved': () => (
    <>
      <rect x="14" y="4" width="20" height="40" rx="3" />
      <path d="M21 38h6M18.5 20l4 4 7-8" />
    </>
  ),
  /** Sending: an arrow leaving a tray. */
  sending: () => <path d="M24 30V8M15 17l9-9 9 9M8 30v8a3 3 0 0 0 3 3h26a3 3 0 0 0 3-3v-8" />,

  /** Income bands: one to four banknotes stacked (more notes, more money). */
  'income-1': () => notes(1),
  'income-2': () => notes(2),
  'income-3': () => notes(3),
  'income-4': () => notes(4),

  // Tracking-code symbols (backend TRACKING_SYMBOLS): everyday things a person can name.
  moon: () => <path d="M31 7a17 17 0 1 0 10 27A14 14 0 0 1 31 7z" />,
  star: () => (
    <path d="M24 6l4.4 11.9 12.7.5-10 7.9 3.5 12.3L24 31.5l-10.6 7.1 3.5-12.3-10-7.9 12.7-.5z" />
  ),
  fish: () => (
    <>
      <path d="M4 24c6-8 14-11 22-9 5 1 8 5 10 9-2 4-5 8-10 9-8 2-16-1-22-9z" />
      <path d="M36 24l8-8v16zM12 22h.01" />
    </>
  ),
  tree: () => (
    <>
      <circle cx="24" cy="17" r="12" />
      <path d="M24 29v14M17 43h14M24 34l-5-5" />
    </>
  ),
  house: () => (
    <>
      <path d="M7 23L24 9l17 14M11 20v22h26V20M31 14V7h5v11" />
      <path d="M19 29h10v8H19z" />
    </>
  ),
  sun: () => (
    <>
      <circle cx="24" cy="24" r="8" />
      <path d="M24 4v6M24 38v6M4 24h6M38 24h6M9.9 9.9l4.2 4.2M33.9 33.9l4.2 4.2M9.9 38.1l4.2-4.2M33.9 14.1l4.2-4.2" />
    </>
  ),
  bird: () => <path d="M4 17c7-4 13-2 20 9 7-11 13-13 20-9M24 26v6" />,
  flower: () => (
    <>
      <circle cx="24" cy="15" r="3.5" />
      <circle cx="24" cy="6.5" r="4.5" />
      <circle cx="32" cy="12.5" r="4.5" />
      <circle cx="29" cy="22" r="4.5" />
      <circle cx="19" cy="22" r="4.5" />
      <circle cx="16" cy="12.5" r="4.5" />
      <path d="M24 26.5V44M24 38c-3-4-7-5-10-4M24 35c3-3 6-4 9-3" />
    </>
  ),
  key: () => (
    <>
      <circle cx="14" cy="24" r="8" />
      <path d="M22 24h22M37 24v7M43 24v5" />
    </>
  ),
  boat: () => (
    <>
      <path d="M5 31h38l-6 9H11z" />
      <path d="M24 31V6l13 19H24" />
    </>
  ),
  lamp: () => (
    <>
      <path d="M5 30h34c-2 7-9 10-17 10S7 37 5 30zM39 30l5-4" />
      <path d="M22 24c-4-3-4-8 0-14 4 6 4 11 0 14z" />
    </>
  ),
  leaf: () => (
    <>
      <path d="M8 40C8 20 20 8 40 8c0 20-12 32-32 32z" />
      <path d="M8 40l20-20" />
    </>
  ),
  cup: () => (
    <>
      <path d="M8 18h26v9a13 13 0 0 1-26 0z" />
      <path d="M34 21h3a5 5 0 0 1 0 10h-4M6 44h30M17 6v6M25 6v6" />
    </>
  ),
  drum: () => (
    <>
      <ellipse cx="24" cy="13" rx="16" ry="5" />
      <path d="M8 13v21c0 3 7 6 16 6s16-3 16-6V13M8 22l8 8 8-8 8 8 8-8" />
    </>
  ),
  kite: () => (
    <>
      <path d="M24 4l14 15-14 19-14-19z" />
      <path d="M10 19h28M24 4v34M24 38c-4 2 4 4 0 7" />
    </>
  ),
  bell: () => (
    <>
      <path d="M24 6a3 3 0 0 1 3 3v1.5A12 12 0 0 1 36 22v9l4 5H8l4-5v-9a12 12 0 0 1 9-11.5V9a3 3 0 0 1 3-3z" />
      <path d="M20 40a4 4 0 0 0 8 0" />
    </>
  ),
} satisfies Record<string, () => JSX.Element>;

/** n banknotes stacked from the bottom; the top one has the coin mark. */
function notes(count: number): JSX.Element {
  const rows = Array.from({ length: count }, (_, index) => 36 - index * 9);
  const top = rows[rows.length - 1] ?? 36;
  return (
    <>
      {rows.map((y) => (
        <rect key={y} x="7" y={y} width="34" height="7" rx="2" />
      ))}
      <path d={`M24 ${top + 3.5}h.01`} />
    </>
  );
}

export type PictogramName = keyof typeof ICONS;

/** Icons that point along the reading direction and so mirror in RTL. */
const DIRECTIONAL: ReadonlySet<PictogramName> = new Set<PictogramName>(['back', 'forward', 'delete']);

export const PICTOGRAM_NAMES = Object.keys(ICONS) as PictogramName[];

/** Names the server may use for the same picture. */
const ALIASES: Readonly<Record<string, PictogramName>> = {
  'person-will-help': 'person-help',
  person_will_help: 'person-help',
  approved: 'yes',
  rejected: 'no',
  needs_proof: 'document',
  proof: 'document',
  money: 'payment',
};

/** A pictogram name from server data, or null when we have no such picture. */
export function pictogramFor(name: string | null | undefined): PictogramName | null {
  if (!name) return null;
  if (Object.prototype.hasOwnProperty.call(ICONS, name)) return name as PictogramName;
  return ALIASES[name] ?? null;
}

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

/**
 * "Do not": the picture with a red slash across it, on a white edge so it
 * stands out from the picture's own lines. Used for "do not pay" and the like.
 */
export function CrossedPictogram({ name, size = 48, class: className = '' }: { name: PictogramName; size?: number; class?: string }) {
  return (
    <span class={`relative inline-flex shrink-0 ${className}`} aria-hidden="true">
      <Pictogram name={name} size={size} />
      <svg
        viewBox="0 0 48 48"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        stroke-linecap="round"
        focusable="false"
        class="absolute inset-0"
      >
        <path d="M7 41L41 7" stroke-width="8" class="text-paper" />
        <path d="M7 41L41 7" stroke-width="4" class="text-danger" />
      </svg>
    </span>
  );
}
