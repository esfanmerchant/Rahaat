import type { ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { homePathFor, login, session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { DemoAccount } from '../../shared/api/types';
import type { components } from '../../shared/api/schema';
import { Emblem } from '../../shared/components/Emblem';
import { PrototypeFooter } from '../../shared/components/PrototypeFooter';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useTemporaryLang } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { formatPhone } from '../phone';
import { StaffRoot, theme, toggleTheme } from '../theme';

type Load =
  | { kind: 'loading' }
  | { kind: 'hidden' }
  | { kind: 'failed'; failure: ApiFailure }
  | { kind: 'ready'; accounts: DemoAccount[] };

type Pulse = components['schemas']['PulseOut'];

const rowKey = (a: DemoAccount): string => `${a.tenant_slug}|${a.identifier}|${a.role}`;

/** WebGL only when it works and neither reduced motion nor Save-Data is on. Never downloads three.js to find out. */
function ambientAllowed(): boolean {
  try {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
    if ((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData === true) return false;
    const probe = document.createElement('canvas');
    const gl = probe.getContext('webgl2') ?? probe.getContext('webgl');
    if (!gl) return false;
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

interface Persona {
  /** Matches the label the demo-accounts endpoint sends. */
  label: string;
  name: string;
  initials: string;
  who: string;
  group: 'people' | 'staff';
  try: readonly string[];
}

/** The seven people a judge can become. Names are invented; the accounts come from the API, not from here. */
const PERSONAS: readonly Persona[] = [
  {
    label: 'Citizen: widow',
    name: 'Zainab',
    initials: 'Z',
    who: 'A widow who cannot read. No income record exists for her.',
    group: 'people',
    try: ['Apply with pictures and voice, and upload her specimen card.', 'See the system ask for one paper instead of guessing.', 'Send a paper it cannot verify: a person is called in.'],
  },
  {
    label: 'Citizen: shopkeeper',
    name: 'Aslam',
    initials: 'A',
    who: 'A shopkeeper with a signed card and a registry income under the cap.',
    group: 'people',
    try: ['Apply with his signed card: the system decides alone.', 'Read the plain reason and the tracking symbols.', 'Paste a fee-and-PIN message into the scam checker.'],
  },
  {
    label: 'Community helper',
    name: 'Rubina',
    initials: 'R',
    who: 'A helper who serves many families from one phone.',
    group: 'people',
    try: ['Open the list of families.', 'Enter one family with that family’s own PIN.', 'Watch the banner that says whom you are helping.'],
  },
  {
    label: 'Officer',
    name: 'Officer',
    initials: 'O',
    who: 'Reviews what the system is not sure about.',
    group: 'staff',
    try: ['Open the queue and press Enter on the top case.', 'Read the briefing and the decision anatomy.', 'Approve or reject; a reason is required.'],
  },
  {
    label: 'Second admin (approves rule changes)',
    name: 'Approver',
    initials: 'Ap',
    who: 'The second pair of eyes on rule changes.',
    group: 'staff',
    try: ['Open Rules and find a version waiting for approval.', 'Compare it with the active version.', 'Publish it: the requester cannot.'],
  },
  {
    label: 'Auditor (both departments)',
    name: 'Auditor',
    initials: 'Au',
    who: 'Checks that decisions can be explained and replayed.',
    group: 'staff',
    try: ['Open a decision: the citizen’s reason beside the full trace.', 'Press Replay and compare the hashes.', 'Verify the audit chain.'],
  },
  {
    label: 'Admin',
    name: 'Admin',
    initials: 'Ad',
    who: 'Owns rules, keys and the Digital Twin.',
    group: 'staff',
    try: ['Edit a rule, dry-run it and request approval.', 'Replay a change on the Digital Twin before it goes live.', 'Run a real call in the Challenge Lab.'],
  },
];

/** An eight-point star (two squares, as in the emblem) with initials inside. */
function StarAvatar({ initials, tone }: { initials: string; tone: 'people' | 'staff' }) {
  const stroke = tone === 'people' ? '#4ee6a6' : '#8ea2ff';
  return (
    <svg viewBox="0 0 64 64" width="56" height="56" aria-hidden="true" class="shrink-0">
      <g fill="rgb(255 255 255 / 0.04)" stroke={stroke} stroke-width="2" stroke-linejoin="round">
        <path d="M14 14h36v36H14z" />
        <path d="M32 5 59 32 32 59 5 32z" />
      </g>
      <circle cx="32" cy="32" r="14" fill="#0b1026" stroke="#ffd36e" stroke-opacity="0.7" />
      <text x="32" y="37" text-anchor="middle" font-size={initials.length > 1 ? 14 : 17} font-weight="800" fill="#eef0ff" font-family="system-ui, sans-serif">
        {initials}
      </text>
    </svg>
  );
}


/** Reveals its children once, the first time it scrolls into view. Without IntersectionObserver it is simply visible. */
function Reveal({ children, class: cls = '', id, label }: { children?: ComponentChildren; class?: string; id?: string; label?: string }) {
  const ref = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <section ref={ref} id={id} aria-labelledby={label} class={`dm-reveal ${cls}`} data-in={seen ? '' : undefined}>
      {children}
    </section>
  );
}

function Heading({ id, kicker, children }: { id: string; kicker: string; children: ComponentChildren }) {
  return (
    <header class="mb-6 max-w-3xl">
      <p class="st-noor-text text-xs font-bold uppercase tracking-[0.25em]">{kicker}</p>
      <h2 id={id} class="mt-1 text-3xl font-black tracking-tight md:text-5xl">
        {children}
      </h2>
    </header>
  );
}

/* ---------- "How Rahat decides": the real thresholds on a bar ---------- */

type ZoneKey = 'reject' | 'person' | 'ask' | 'approve';
const ZONE: Record<ZoneKey, { label: string; tone: 'bad' | 'info' | 'warn' | 'ok'; why: string }> = {
  reject: {
    label: 'Reject',
    tone: 'bad',
    why: 'Almost certainly not eligible. The system rejects alone only when a hard rule fails on verified input. If the input is not verified, a person checks instead.',
  },
  person: {
    label: 'A person will check',
    tone: 'info',
    why: 'Not sure enough to decide alone, either way. The case goes to an officer with a briefing: what was understood, what is unsure, and what proof would settle it.',
  },
  ask: {
    label: 'Ask for proof',
    tone: 'warn',
    why: 'Probably eligible, but not enough to pay alone. The system asks for one more paper instead of guessing.',
  },
  approve: {
    label: 'Approve',
    tone: 'ok',
    why: 'At or above the approve threshold. It approves alone only if every hard rule also passes on verified input; otherwise a person checks.',
  },
};

function Explainer() {
  const [load, setLoad] = useState<{ kind: 'loading' } | { kind: 'failed'; failure: ApiFailure } | { kind: 'ready'; pulse: Pulse }>({ kind: 'loading' });
  const [p, setP] = useState(0.5);
  const fetchPulse = async (): Promise<void> => {
    setLoad({ kind: 'loading' });
    const r = await call(api.GET('/v1/public/pulse'));
    setLoad(r.ok ? { kind: 'ready', pulse: r.data } : { kind: 'failed', failure: r.failure });
  };
  useEffect(() => {
    void fetchPulse();
  }, []);

  if (load.kind === 'loading') return <div role="status" aria-label="Loading the thresholds" class="rh-skeleton h-40" />;
  if (load.kind === 'failed') return <FailureState failure={load.failure} density="staff" heading="h2" onRetry={() => void fetchPulse()} />;
  const t = load.pulse.replay.headline?.thresholds;
  if (!t) return <ScreenState kind="empty" density="staff" heading="h2" title="No thresholds yet" body="The replay is not available on this deployment, so there is nothing to mark on the bar." />;

  const rejectAt = 1 - t.reject; // the reject test reads P(ineligible); on the p_ok scale it sits at 1 minus it
  const zoneOf = (v: number): ZoneKey => (v <= rejectAt ? 'reject' : v >= t.approve ? 'approve' : v >= t.confidence_floor ? 'ask' : 'person');
  const z = zoneOf(p);
  const info = ZONE[z];
  const bands: { key: ZoneKey; from: number; to: number }[] = [
    { key: 'reject', from: 0, to: rejectAt },
    { key: 'person', from: rejectAt, to: t.confidence_floor },
    { key: 'ask', from: t.confidence_floor, to: t.approve },
    { key: 'approve', from: t.approve, to: 1 },
  ];
  const marks = [
    { x: rejectAt, label: `reject at or below ${rejectAt.toFixed(3)}`, row: 0 },
    { x: t.confidence_floor, label: `confidence floor ${t.confidence_floor.toFixed(2)}`, row: 1 },
    { x: t.approve, label: `approve at ${t.approve.toFixed(3)}`, row: 0 },
  ];
  return (
    <div class="grid items-start gap-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <div class="st-panel p-5 md:p-7">
        <label for="pok" class="flex items-baseline justify-between gap-3 text-sm text-ink-muted">
          <span>
            What the model believes: <span class="font-mono">p_ok</span>, the chance this person is eligible and genuine
          </span>
          <output class="rh-num text-3xl font-black text-ink" aria-live="off">
            {p.toFixed(3)}
          </output>
        </label>
        <div class="relative mt-10 mb-20 select-none">
          <div class="dm-bar flex h-6 overflow-hidden rounded-full" aria-hidden="true">
            {bands.map((b) => (
              <i key={b.key} class={`dm-band dm-${b.key} ${z === b.key ? 'on' : ''}`} style={{ width: `${(b.to - b.from) * 100}%` }} />
            ))}
          </div>
          <span class={`dm-marker dm-m-${info.tone}`} style={{ insetInlineStart: `${p * 100}%` }} aria-hidden="true" />
          {marks.map((m) => (
            <span key={m.label} class={`dm-tick ${m.x < 0.25 ? 'dm-tick-l' : m.x > 0.95 ? 'dm-tick-r' : ''}`} style={{ insetInlineStart: `${m.x * 100}%`, '--row': m.row }}>
              <b />
              <span class="rh-ltr">{m.label}</span>
            </span>
          ))}
          <input
            id="pok"
            type="range"
            min="0"
            max="1"
            step="0.001"
            value={p}
            onInput={(e) => setP(Number(e.currentTarget.value))}
            class="dm-range absolute inset-x-0 -top-3 h-12 w-full"
            aria-valuetext={`p_ok ${p.toFixed(3)}: ${info.label}`}
          />
        </div>
        <p class="text-xs text-ink-subtle">
          Thresholds are the live ones from the cost matrix ({load.pulse.replay.replay_source}). The reject test reads P(ineligible), so it is drawn at 1 minus its value. Simplified: the engine chooses the cheapest action by expected cost.{' '}
          <a href="/staff/costs">See the cost page</a> for the detail.
        </p>
      </div>
      <div class={`st-panel dm-verdict st-tone-${info.tone} p-5 md:p-7`} aria-live="polite" data-testid="verdict">
        <p class="text-xs font-bold uppercase tracking-widest text-ink-muted">At p_ok {p.toFixed(3)}</p>
        <p class="dm-verdict-label mt-1 text-4xl font-black leading-tight tracking-tight md:text-5xl">{info.label}</p>
        <p class="mt-3 text-lg text-ink-muted">{info.why}</p>
      </div>
    </div>
  );
}

/**
 * /demo: a cinematic front door for judges. A dim, slow Loom of Light behind the title (WebGL only when it works and
 * neither reduced motion nor Save-Data is on, else the night sky), then the people, how Rahat decides, who runs it and
 * what it will never do. Mock accounts with one-tap sign-in come from the demo-accounts endpoint. Lazy chunk.
 */
export default function DemoPage() {
  useTemporaryLang('en');
  const { route } = useLocation();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [pending, setPending] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ key: string; message: string } | null>(null);
  const [ambientOn, setAmbientOn] = useState(false);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const [pulse, setPulse] = useState<Pulse | null>(null);

  const fetchAccounts = async (): Promise<void> => {
    setLoad({ kind: 'loading' });
    const result = await call(api.GET('/v1/demo/accounts'));
    if (result.ok) setLoad({ kind: 'ready', accounts: result.data.accounts });
    else if (result.failure.kind === 'not_found') setLoad({ kind: 'hidden' });
    else setLoad({ kind: 'failed', failure: result.failure });
  };

  useEffect(() => {
    void fetchAccounts();
    void call(api.GET('/v1/public/pulse')).then((r) => r.ok && setPulse(r.data));
  }, []);

  // The ambient scene: only when WebGL works and neither reduced motion nor Save-Data is on. three.js is fetched here and nowhere else.
  useEffect(() => {
    if (!canvas.current || !host.current || !ambientAllowed()) return;
    let dispose: (() => void) | null = null;
    let cancelled = false;
    void import('../../live/sceneAmbient')
      .then((m) => m.mountAmbient(canvas.current as HTMLCanvasElement, host.current as HTMLElement, () => setAmbientOn(false)))
      .then((d) => {
        if (cancelled) d?.();
        else if (d) {
          dispose = d;
          setAmbientOn(true);
        }
      })
      .catch(() => setAmbientOn(false));
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, []);

  const use = async (account: DemoAccount): Promise<void> => {
    const key = rowKey(account);
    setPending(key);
    setRowError(null);
    const result = await login({ identifier: account.identifier, secret: account.secret, tenant_slug: account.tenant_slug });
    setPending(null);
    if (result.ok) {
      route(homePathFor(result.role));
      return;
    }
    const f = result.failure;
    setRowError({
      key,
      message: f.kind === 'offline' ? 'No network.' : `Sign-in failed${f.status ? ` (${f.status})` : ''}${f.problem ? `: ${f.problem.title}` : ''}.`,
    });
  };

  const current = session.value;
  const night = theme.value === 'night';
  const found = useMemo(
    () =>
      load.kind === 'ready'
        ? PERSONAS.map((p) => ({ p, a: load.accounts.find((a) => a.label === p.label && a.tenant_slug === 'sindh-relief') })).filter((x): x is { p: Persona; a: DemoAccount } => Boolean(x.a))
        : [],
    [load],
  );
  const zainab = found.find((x) => x.p.name === 'Zainab');
  const headline = pulse?.replay.headline ?? null;

  const card = (p: Persona, account: DemoAccount, i: number) => {
    const key = rowKey(account);
    const isPhone = /^0999-\d{7}$/.test(account.identifier);
    return (
      <li key={key} class="st-panel dm-card flex flex-col gap-3 p-5" style={{ '--i': i }}>
        <div class="flex items-center gap-3">
          <StarAvatar initials={p.initials} tone={p.group} />
          <div class="min-w-0">
            <h3 class="text-xl font-black leading-tight tracking-tight">{p.name}</h3>
            <p class="text-xs text-ink-muted">
              <span class="font-mono">{account.role}</span> · {account.kind === 'citizen' || account.role === 'helper' ? 'citizen app' : 'staff console'}
            </p>
          </div>
        </div>
        <p class="text-ink-muted">{p.who}</p>
        <div>
          <p class="st-noor-text text-xs font-bold uppercase tracking-widest">What to try</p>
          <ol class="mt-1 flex flex-col gap-1 ps-5 text-sm">
            {p.try.map((t) => (
              <li key={t} class="list-decimal marker:font-mono marker:text-ink-subtle">
                {t}
              </li>
            ))}
          </ol>
        </div>
        <div class="mt-auto flex flex-wrap items-end justify-between gap-2 pt-1">
          <p class="rh-ltr font-mono text-xs text-ink-subtle">
            {isPhone ? formatPhone(account.identifier) : account.identifier}
            <br />
            {account.secret}
          </p>
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => void use(account)}
            class="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border-2 border-primary bg-primary px-4 font-semibold text-white transition-colors hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={`Sign in as ${p.name}`}
          >
            {pending === key ? 'Signing in…' : `Sign in as ${p.name}`}
          </button>
        </div>
        {rowError?.key === key ? (
          <p role="alert" class="text-danger">
            {rowError.message}
          </p>
        ) : null}
      </li>
    );
  };

  const people = found.filter((x) => x.p.group === 'people');
  const staff = found.filter((x) => x.p.group === 'staff');
  const stateBody =
    load.kind === 'loading' ? (
      <ScreenState kind="loading" density="staff" />
    ) : load.kind === 'hidden' ? (
      <ScreenState kind="not_found" density="staff" title="Page not found" body="This page does not exist." />
    ) : load.kind === 'failed' ? (
      <FailureState failure={load.failure} density="staff" onRetry={() => void fetchAccounts()} />
    ) : found.length === 0 ? (
      <ScreenState kind="empty" density="staff" title="No demo accounts" body="Run the seed (npm run seed) to create them." />
    ) : null;

  return (
    <StaffRoot>
      <header ref={host} class="dm-hero relative isolate flex min-h-dvh flex-col overflow-hidden">
        <div class="dm-sky absolute inset-0 -z-20" aria-hidden="true" />
        <canvas ref={canvas} class={`dm-canvas absolute inset-0 -z-10 h-full w-full ${ambientOn ? 'on' : ''}`} aria-hidden="true" tabIndex={-1} />
        <div class="dm-dim absolute inset-0 -z-[5]" aria-hidden="true" />
        <div class="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between gap-3 px-6 py-4 text-sm text-night-muted">
          <span class="rounded-full border border-night-line px-2 font-mono text-xs uppercase tracking-wide">Prototype</span>
          <span class="flex items-center gap-3">
            <span>{current.status === 'signed-in' ? `Signed in as ${current.user.display_name} (${current.active.role}).` : 'Not signed in.'}</span>
            <button type="button" onClick={toggleTheme} aria-pressed={night} class="min-h-9 rounded-lg border border-night-line px-3 text-night-ink hover:bg-night-3">
              {night ? 'Night' : 'Day'} theme
            </button>
          </span>
        </div>
        <div class="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col items-center justify-center gap-6 px-6 pb-24 text-center">
          <Emblem size={170} tone="night" animate class="drop-shadow-glow" />
          <h1 ref={headingRef} tabIndex={-1} class="dm-title dm-h1 flex flex-wrap items-baseline justify-center gap-x-6 font-black tracking-tight text-night-ink">
            Rahat
            <span lang="ur" dir="rtl" class="dm-h1-ur font-bold text-noor">
              راحت
            </span>
          </h1>
          <p class="dm-lede max-w-2xl text-xl text-night-ink md:text-2xl">
            A relief-payment platform that decides, explains and protects, and says “I am not sure” when it is not.
          </p>
          <div class="flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              disabled={!zainab || pending !== null}
              onClick={() => zainab && void use(zainab.a)}
              class="inline-flex min-h-12 items-center gap-2 rounded-xl bg-noor px-6 text-lg font-black text-night shadow-glow hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {zainab && pending === rowKey(zainab.a) ? 'Signing in…' : 'Try it as Zainab'}
            </button>
            <a
              href="/live"
              class="inline-flex min-h-12 items-center gap-2 rounded-xl border-2 border-night-line bg-night/60 px-6 text-lg font-bold text-night-ink no-underline hover:bg-night-3"
            >
              <span class="st-live" aria-hidden="true" />
              Watch the engine
            </a>
          </div>
          {zainab && rowError?.key === rowKey(zainab.a) ? (
            <p role="alert" class="rounded-md bg-danger-soft px-3 py-1 text-danger">
              {rowError.message}
            </p>
          ) : null}
          <p class="max-w-xl text-sm text-night-muted">Every account, number and record here is simulated. Mock accounts for judges and testing.</p>
        </div>
        <a href="#people" class="dm-cue absolute inset-x-0 bottom-5 z-10 mx-auto flex w-fit flex-col items-center gap-1 text-xs uppercase tracking-widest text-night-muted no-underline" aria-label="Scroll to the people it serves">
          Scroll
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M3 6l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </a>
      </header>

      <main class="mx-auto w-full max-w-7xl flex-1 px-6 pb-8">
        {stateBody ? <div class="py-16">{stateBody}</div> : null}
        {found.length > 0 ? (
          <>
            <Reveal id="people" label="people-h" class="py-20">
              <Heading id="people-h" kicker="01 · Who it is for">
                The people it serves
              </Heading>
              <ul class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{people.map((x, i) => card(x.p, x.a, i))}</ul>
            </Reveal>

            <Reveal id="decides" label="decides-h" class="py-20">
              <Heading id="decides-h" kicker="02 · The heart of it">
                How Rahat decides
              </Heading>
              <p class="mb-6 max-w-3xl text-lg text-ink-muted">Slide the model’s belief and watch what the system does. The marks are the real thresholds it runs on right now.</p>
              <Explainer />
            </Reveal>

            <Reveal id="staff" label="staff-h" class="py-20">
              <Heading id="staff-h" kicker="03 · Behind the desk">
                The people who run it
              </Heading>
              <ul class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{staff.map((x, i) => card(x.p, x.a, i))}</ul>
            </Reveal>

            <Reveal id="never" label="never-h" class="py-20">
              <Heading id="never-h" kicker="04 · Lines it does not cross">
                What it will never do
              </Heading>
              <ul class="grid gap-4 md:grid-cols-3">
                <li class="st-panel dm-card st-tone-ok p-6" style={{ '--i': 0 }}>
                  <p class="st-tile-num rh-num dm-big font-black leading-none">{headline ? headline.silent_guesses : '·'}</p>
                  <h3 class="mt-3 text-2xl font-black tracking-tight">It never guesses silently</h3>
                  <p class="mt-2 text-ink-muted">
                    {headline
                      ? `Silent guesses: ${headline.silent_guesses}, in a replay of ${headline.cases.toLocaleString('en-US')} labelled cases. When it is unsure it asks for proof or hands the case to a person.`
                      : 'When it is unsure it asks for proof or hands the case to a person.'}
                  </p>
                </li>
                <li class="st-panel dm-card st-tone-info p-6" style={{ '--i': 1 }}>
                  <p class="st-tile-num rh-ltr whitespace-nowrap font-mono text-2xl font-black leading-tight md:text-3xl">+92 999NNNNNNN</p>
                  <h3 class="mt-3 text-2xl font-black tracking-tight">It never uses real people’s data</h3>
                  <p class="mt-2 text-ink-muted">Every name, ID and phone number is invented. Mock IDs look like 00000-NNNNNNN-C. No real ID image is ever processed.</p>
                </li>
                <li class="st-panel dm-card st-tone-bad p-6" style={{ '--i': 2 }}>
                  <p class="st-tile-num text-3xl font-black leading-tight md:text-4xl">A person will check</p>
                  <h3 class="mt-3 text-2xl font-black tracking-tight">It never shows detection details to citizens</h3>
                  <p class="mt-2 text-ink-muted">Why a message or a paper was flagged is for staff and auditors. The citizen hears one calm sentence.</p>
                </li>
              </ul>
            </Reveal>
          </>
        ) : null}
      </main>
      <PrototypeFooter density="staff" />
    </StaffRoot>
  );
}
