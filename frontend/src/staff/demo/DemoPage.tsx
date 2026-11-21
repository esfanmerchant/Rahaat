import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { homePathFor, login, session } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { DemoAccount } from '../../shared/api/types';
import { Emblem } from '../../shared/components/Emblem';
import { PrototypeFooter } from '../../shared/components/PrototypeFooter';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useTemporaryLang } from '../../shared/i18n';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { StaffRoot, theme, toggleTheme } from '../theme';

type Load =
  | { kind: 'loading' }
  | { kind: 'hidden' }
  | { kind: 'failed'; failure: ApiFailure }
  | { kind: 'ready'; accounts: DemoAccount[] };

const rowKey = (a: DemoAccount): string => `${a.tenant_slug}|${a.identifier}|${a.role}`;

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

/**
 * /demo: the judges' briefing room and front door. Mock accounts with one-tap sign-in, from the demo-accounts
 * endpoint. Lazy chunk. Looks like any unknown page when the API answers 404 (outside demo and dev).
 */
export default function DemoPage() {
  useTemporaryLang('en');
  const { route } = useLocation();
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [pending, setPending] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ key: string; message: string } | null>(null);
  const headingRef = useFocusOnMount<HTMLHeadingElement>(load.kind === 'ready');

  const fetchAccounts = async (): Promise<void> => {
    setLoad({ kind: 'loading' });
    const result = await call(api.GET('/v1/demo/accounts'));
    if (result.ok) setLoad({ kind: 'ready', accounts: result.data.accounts });
    else if (result.failure.kind === 'not_found') setLoad({ kind: 'hidden' });
    else setLoad({ kind: 'failed', failure: result.failure });
  };

  useEffect(() => {
    void fetchAccounts();
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

  const card = (p: Persona, account: DemoAccount) => {
    const key = rowKey(account);
    return (
      <li key={key} class="st-panel flex flex-col gap-3 p-4">
        <div class="flex items-center gap-3">
          <StarAvatar initials={p.initials} tone={p.group} />
          <div class="min-w-0">
            <h3 class="text-lg font-black leading-tight tracking-tight">{p.name}</h3>
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
            {account.identifier}
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

  let body;
  if (load.kind === 'loading') body = <ScreenState kind="loading" density="staff" />;
  else if (load.kind === 'hidden') body = <ScreenState kind="not_found" density="staff" title="Page not found" body="This page does not exist." />;
  else if (load.kind === 'failed') body = <FailureState failure={load.failure} density="staff" onRetry={() => void fetchAccounts()} />;
  else if (load.accounts.length === 0) body = <ScreenState kind="empty" density="staff" title="No demo accounts" body="Run the seed (npm run seed) to create them." />;
  else {
    const found = PERSONAS.map((p) => ({ p, a: (load.accounts as DemoAccount[]).find((a) => a.label === p.label && a.tenant_slug === 'sindh-relief') })).filter((x): x is { p: Persona; a: DemoAccount } => Boolean(x.a));
    const people = found.filter((x) => x.p.group === 'people');
    const staff = found.filter((x) => x.p.group === 'staff');
    body = (
      <div class="flex flex-col gap-8">
        <section aria-labelledby="people-h">
          <h2 id="people-h" class="mb-3 text-xs font-bold uppercase tracking-widest text-ink-muted">
            The people it serves
          </h2>
          <ul class="rh-stagger grid gap-4 md:grid-cols-2 xl:grid-cols-3">{people.map((x) => card(x.p, x.a))}</ul>
        </section>
        <section aria-labelledby="staff-h">
          <h2 id="staff-h" class="mb-3 text-xs font-bold uppercase tracking-widest text-ink-muted">
            The people who run it
          </h2>
          <ul class="rh-stagger grid gap-4 md:grid-cols-2 xl:grid-cols-4">{staff.map((x) => card(x.p, x.a))}</ul>
        </section>
      </div>
    );
  }

  return (
    <StaffRoot>
      <header class="rh-night-sky rh-lattice-night relative overflow-hidden border-b border-night-line">
        <div class="mx-auto flex w-full max-w-7xl flex-col items-center gap-6 px-6 py-10 text-center md:flex-row md:text-start">
          <Emblem size={150} tone="night" animate class="drop-shadow-glow" />
          <div class="flex flex-1 flex-col gap-3">
            <p class="text-xs font-bold uppercase tracking-[0.25em] text-noor">Judges’ briefing room</p>
            <h1 ref={headingRef} tabIndex={-1} class="flex flex-wrap items-baseline justify-center gap-x-5 text-5xl font-black tracking-tight md:justify-start md:text-7xl">
              Rahat
              <span lang="ur" dir="rtl" class="text-4xl font-bold text-noor md:text-5xl">
                راحت
              </span>
            </h1>
            <p class="max-w-3xl text-lg text-night-ink md:text-xl">
              A relief-payment platform that decides, explains and protects, and that says “I am not sure” and hands the case to a person with everything they need.
            </p>
            <div class="flex flex-wrap items-center justify-center gap-3 md:justify-start">
              <a
                href="/live"
                class="inline-flex min-h-11 items-center gap-2 rounded-lg bg-noor px-5 font-black text-night no-underline shadow-glow hover:brightness-105"
              >
                <span class="st-live" aria-hidden="true" />
                Watch it live
              </a>
              <button type="button" onClick={toggleTheme} aria-pressed={night} class="min-h-11 rounded-lg border border-night-line px-4 text-night-ink hover:bg-night-3">
                {night ? 'Night' : 'Day'} theme
              </button>
              <span class="text-sm text-night-muted">
                {current.status === 'signed-in' ? `Signed in as ${current.user.display_name} (${current.active.role}).` : 'Not signed in. Pick someone below.'}
              </span>
            </div>
          </div>
        </div>
      </header>
      <main class="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <p class="mb-5 rounded-lg border border-warning-ink bg-warning-soft px-3 py-2 text-warning-ink">
          Mock accounts for judges and testing. Every account, number and record here is simulated. Citizen and helper accounts open the citizen app at /; staff accounts open the console at /staff.
        </p>
        {body}
      </main>
      <PrototypeFooter density="staff" />
    </StaffRoot>
  );
}
