import { useState } from 'preact/hooks';
import { Emblem } from '../../shared/components/Emblem';
import { PrototypeFooter } from '../../shared/components/PrototypeFooter';
import { useTemporaryLang } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { formatPhone } from '../phone';
import { StaffRoot, theme, toggleTheme } from '../theme';

/**
 * Demo kit: the fictional specimen cards (data/demo_cards, copied to public/demo-cards) for testing the
 * upload step by hand. Every label below was measured with the app's own document check on 22 Nov:
 * all 30 files give the result shown, with or without OCR. The labels say what was done to each test
 * card, not how the check spots it (detection details stay in staff and auditor views).
 */

type Outcome = 'pass' | 'retake' | 'person';

interface Variant {
  file: string;
  title: string;
  what: string;
  outcome: Outcome;
}

const VARIANTS: readonly Variant[] = [
  { file: 'card.png', title: 'Flat card', what: 'The card itself. Print it, or show it on a screen to the camera.', outcome: 'pass' },
  { file: 'clean.jpg', title: 'Clean photo', what: 'A normal phone photo of the card.', outcome: 'pass' },
  { file: 'glare.jpg', title: 'Light glare', what: 'Some glare, but the QR code is clear.', outcome: 'pass' },
  { file: 'blurry.jpg', title: 'Blurry photo', what: 'Too blurry to read.', outcome: 'retake' },
  { file: 'glare_qr.jpg', title: 'Glare on the QR', what: 'Light hides the QR code.', outcome: 'retake' },
  { file: 'cropped.jpg', title: 'Cut off', what: 'Part of the card is outside the photo.', outcome: 'retake' },
  { file: 'altered.jpg', title: 'Edited name', what: 'The printed name was changed in an image editor.', outcome: 'person' },
  { file: 'wrong_qr.jpg', title: 'Someone else’s QR', what: 'The QR code was copied from another person’s card.', outcome: 'person' },
  { file: 'unknown_issuer.jpg', title: 'Unknown issuer', what: 'Signed by an issuer Rahat does not trust.', outcome: 'person' },
  { file: 'bad_signature.jpg', title: 'Broken signature', what: 'The QR data was changed after signing.', outcome: 'person' },
];

const OUTCOMES: Record<Outcome, { label: string; tone: string; note: string }> = {
  pass: { label: 'Passes the card check', tone: 'st-tone-ok', note: 'The card is accepted and the application moves on.' },
  retake: { label: 'Asks for a new photo', tone: 'st-tone-warn', note: 'The person is asked, in simple words, to take the photo again.' },
  person: { label: 'A person checks', tone: 'st-tone-bad', note: 'Nothing is decided by the machine. The citizen hears “a person will check”.' },
};

interface Person {
  slug: string;
  name: string;
  nameUr: string;
  role: string;
  mockId: string;
  district: string;
  department: string;
  phone: string;
}

const PEOPLE: readonly Person[] = [
  { slug: 'zainab-bibi', name: 'Zainab Bibi', nameUr: 'زینب بی بی', role: 'Widow', mockId: '00000-1000201-2', district: 'Karachi East',
    department: 'Sindh Relief', phone: '0999-0000201' },
  { slug: 'aslam-khan', name: 'Aslam Khan', nameUr: 'اسلم خان', role: 'Shopkeeper', mockId: '00000-1000202-0', district: 'Hyderabad',
    department: 'Sindh Relief', phone: '0999-0000202' },
  { slug: 'rukhsana-parveen', name: 'Rukhsana Parveen', nameUr: 'رخسانہ پروین', role: 'Citizen, second department', mockId: '00000-1000301-0',
    district: 'Lahore', department: 'Punjab Relief', phone: '0999-0000301' },
];

const DEMO_PIN = '4826';

export default function DemoKitPage() {
  useTemporaryLang('en');
  const headingRef = useFocusOnMount<HTMLHeadingElement>(false);
  const [slug, setSlug] = useState(PEOPLE[0]?.slug ?? '');
  const person = PEOPLE.find((p) => p.slug === slug) ?? PEOPLE[0];
  const night = theme.value === 'night';

  return (
    <StaffRoot>
      <main id="main" class="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-6 md:px-6 md:py-10">
        <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
          <a href="/demo" class="inline-flex min-h-12 items-center gap-2 rounded-lg px-2 font-semibold">
            <span aria-hidden="true">←</span> Back to the demo
          </a>
          <span class="flex items-center gap-3">
            <span class="rounded-full border border-line-strong px-2 font-mono text-xs uppercase tracking-wide">Prototype</span>
            <button type="button" onClick={toggleTheme} aria-pressed={night} class="min-h-12 rounded-lg border border-line-strong px-3">
              {night ? 'Day' : 'Night'}
            </button>
          </span>
        </div>

        <header class="flex flex-col items-start gap-4 md:flex-row md:items-center">
          <Emblem size={72} tone={night ? 'night' : 'paper'} animate />
          <div>
            <h1 ref={headingRef} tabIndex={-1} class="text-4xl font-black tracking-tight md:text-5xl">
              Demo kit
            </h1>
            <p class="mt-2 max-w-3xl text-lg text-ink-muted">
              Fictional specimen cards for testing the upload step. Invented people, mock <span class="rh-ltr font-mono">00000-</span> numbers.
              Not a real ID.
            </p>
          </div>
        </header>

        <ol class="grid gap-3 md:grid-cols-3" aria-label="How to test">
          {[
            ['Sign in', 'Use the phone and PIN below, or one tap on the demo page.'],
            ['Upload a card', 'Start an application. At the card step, upload a file from here, or point the camera at this screen.'],
            ['Try a bad one', 'A bad photo asks for a retake. A forged card goes to a person. Nothing bad is approved.'],
          ].map(([title, body], index) => (
            <li key={title} class="st-panel st-tone-info flex gap-3 p-4">
              <span class="rh-num text-3xl font-black leading-none" aria-hidden="true">
                {index + 1}
              </span>
              <span>
                <strong class="block text-lg">{title}</strong>
                <span class="text-ink-muted">{body}</span>
              </span>
            </li>
          ))}
        </ol>

        <section aria-labelledby="people-h" class="flex flex-col gap-4">
          <h2 id="people-h" class="text-2xl font-black tracking-tight">
            Pick a person
          </h2>
          <div class="flex flex-wrap gap-2" role="group" aria-label="Person">
            {PEOPLE.map((p) => (
              <button
                key={p.slug}
                type="button"
                aria-pressed={p.slug === slug}
                onClick={() => setSlug(p.slug)}
                class={`min-h-12 rounded-full border px-4 font-semibold ${p.slug === slug ? 'border-noor bg-noor text-night' : 'border-line-strong'}`}
              >
                {p.name}
              </button>
            ))}
          </div>

          {person ? (
            <div class="st-panel grid gap-x-8 gap-y-2 p-5 sm:grid-cols-2 lg:grid-cols-4" data-testid="kit-person">
              <p>
                <span class="block text-xs uppercase tracking-widest text-ink-muted">Name</span>
                <span class="text-lg font-bold">{person.name}</span>{' '}
                <span lang="ur" dir="rtl" class="text-ink-muted">
                  {person.nameUr}
                </span>
              </p>
              <p>
                <span class="block text-xs uppercase tracking-widest text-ink-muted">Mock ID</span>
                <span class="rh-ltr font-mono text-lg">{person.mockId}</span>
              </p>
              <p>
                <span class="block text-xs uppercase tracking-widest text-ink-muted">Sign in</span>
                <span class="rh-ltr font-mono text-lg">{formatPhone(person.phone)}</span>
                <span class="text-ink-muted"> · PIN </span>
                <span class="rh-ltr font-mono text-lg">{DEMO_PIN}</span>
              </p>
              <p>
                <span class="block text-xs uppercase tracking-widest text-ink-muted">
                  {person.role} · {person.department}
                </span>
                <span class="text-lg">{person.district}</span>
              </p>
            </div>
          ) : null}
        </section>

        {person
          ? (['pass', 'retake', 'person'] as const).map((outcome) => {
              const info = OUTCOMES[outcome];
              const items = VARIANTS.filter((v) => v.outcome === outcome);
              return (
                <section key={`${person.slug}-${outcome}`} aria-labelledby={`kit-${outcome}`} class="flex flex-col gap-3">
                  <div>
                    <h2 id={`kit-${outcome}`} class="text-xl font-black tracking-tight">
                      {info.label}
                    </h2>
                    <p class="text-ink-muted">{info.note}</p>
                  </div>
                  <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    {items.map((v) => {
                      const src = `/demo-cards/${person.slug}/${v.file}`;
                      return (
                        <li key={v.file} class={`st-panel ${info.tone} flex flex-col overflow-hidden`}>
                          <a href={src} target="_blank" rel="noopener" class="block bg-black/20" aria-label={`Open ${v.title} full size`}>
                            <img
                              src={src}
                              alt={`${v.title}: specimen card of ${person.name}`}
                              loading="lazy"
                              decoding="async"
                              width={1120}
                              height={840}
                              class="aspect-[4/3] w-full object-contain"
                            />
                          </a>
                          <div class="flex flex-1 flex-col gap-1 p-4">
                            <h3 class="text-lg font-bold">{v.title}</h3>
                            <p class="flex-1 text-sm text-ink-muted">{v.what}</p>
                            <a
                              href={src}
                              download={`${person.slug}-${v.file}`}
                              class="mt-2 inline-flex min-h-12 items-center justify-center rounded-lg border border-line-strong px-4 font-semibold"
                            >
                              Download
                            </a>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })
          : null}

        <p class="text-sm text-ink-muted">
          Measured on 22 Nov 2026 with the app’s own document check: all 30 files give the result shown above, with or without OCR.
        </p>
      </main>
      <PrototypeFooter density="staff" />
    </StaffRoot>
  );
}
