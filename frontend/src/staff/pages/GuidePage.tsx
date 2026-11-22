import { useMemo, useState } from 'preact/hooks';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { activeRole } from '../scam';
import { findNavItem, type StaffRole } from '../nav';
import { INPUT } from '../ui';
import './guide.css';

/**
 * "Where is what": the problem statement mapped to the live app. Every place below is a real route (staff routes
 * are in nav.ts, citizen routes in citizen/routes.tsx). Nothing here is fetched; it is a static map.
 * Roles to sign in as come from the /demo sign-in list.
 */
type Place =
  | { kind: 'staff'; slug: string; label?: string }
  | { kind: 'citizen'; label: string; who: 'Zainab or Aslam' | 'Rubina (helper)' | 'anyone' }
  | { kind: 'public'; label: string; href: string }
  | { kind: 'api'; label: string; href: string };

interface Row {
  req: string;
  places: Place[];
  look: string;
}
interface Group {
  id: string;
  title: string;
  rows: Row[];
}

const S = (slug: string, label?: string): Place => (label ? { kind: 'staff', slug, label } : { kind: 'staff', slug });
const C = (label: string, who: 'Zainab or Aslam' | 'Rubina (helper)' | 'anyone' = 'Zainab or Aslam'): Place => ({ kind: 'citizen', label, who });
const P = (label: string, href: string): Place => ({ kind: 'public', label, href });

const GROUPS: Group[] = [
  {
    id: 'constraints',
    title: 'The 8 constraints',
    rows: [
      { req: 'Wrong approvals cost more than slow ones', places: [S('costs')], look: 'The five costs, then expected cost against the auto-approve threshold.' },
      { req: 'Weak internet', places: [C('Citizen app /apply'), P('Feature-phone simulator', '/ussd')], look: 'Go offline mid-form: answers are kept and sent later. /ussd works with no app at all.' },
      { req: 'Low literacy', places: [C('Citizen app /'), P('Feature-phone simulator', '/ussd')], look: 'Voice prompts, big icons, one question per screen; Urdu and right to left.' },
      { req: 'Rules change without notice', places: [S('rules')], look: 'Edit a draft, dry run, request approval, second admin publishes, rollback.' },
      { req: 'Bad data', places: [S('duplicates')], look: 'Possible duplicate people and spelling variants, each with a reason to merge or keep.' },
      { req: 'Explainable decisions', places: [S('decisions')], look: 'Open one decision: plain reason beside the full trace, with replay.' },
      { req: 'User control of data', places: [C('Citizen app /my-data'), S('audit')], look: 'See who holds data, withdraw; then find the consent rows in the audit log.' },
      { req: '"I am not sure"', places: [S('queue')], look: 'Open a case: the handoff package comes first, with the two leading hypotheses.' },
    ],
  },
  {
    id: 'challenges',
    title: 'The 8 technical challenges',
    rows: [
      { req: '01 The cost of being wrong', places: [S('costs'), S('lab', 'Challenge Lab card 1')], look: 'Card 1 runs three real cases and shows the expected cost of each action.' },
      { req: '02 Saying "I am not sure"', places: [S('queue'), S('lab', 'Lab card 2')], look: 'Card 2 sends an ambiguous case to a person; the silent-guess counter stays 0.' },
      { req: '03 Bad data', places: [S('duplicates'), S('lab', 'Lab card 3')], look: 'Mohammad against Muhammed becomes "possible duplicate"; garbage gets a repairable 422.' },
      { req: '04 Rules that change', places: [S('rules'), S('twin')], look: 'Run a draft in the Digital Twin; old decisions keep the rule version they used.' },
      { req: '05 Explain and audit', places: [S('decisions'), S('audit')], look: 'Two views of one decision; verify the audit hash chain.' },
      { req: '06 Consent and take-back', places: [S('lab', 'Lab card 6'), C('Citizen app /my-data')], look: 'Card 6: officer reads (200), citizen withdraws, officer reads again (403), audit shows it.' },
      { req: '07 Works for everyone', places: [S('lab', 'Lab card 7'), P('Feature-phone simulator', '/ussd')], look: 'Card 7 checks size and offline; /ussd is the no-smartphone path.' },
      { req: '08 Scams and fake documents', places: [S('scam-reports'), S('mistakes')], look: 'Flagged messages with reasons; the ledger counts false alarms and misses.' },
    ],
  },
  {
    id: 'core',
    title: 'Core platform features',
    rows: [
      { req: 'Secure login with role-based access', places: [P('Sign-in list', '/demo')], look: 'One-tap accounts per role. Open a page of another role: the page says no, and the server refuses the calls too.' },
      { req: 'Dashboard with progress and history', places: [S('overview'), C('Citizen app /track')], look: 'Overview: live tiles and charts. /track: the citizen\'s own tracker.' },
      { req: 'Case management', places: [S('queue')], look: 'Open a case to decide, request proof or escalate, each with a written reason.' },
      { req: 'Public REST API with keys and docs', places: [S('keys'), { kind: 'api', label: 'API docs /docs', href: '/docs' }], look: 'Create a key (shown once); the docs page is the OpenAPI explorer.' },
      { req: 'Audit log of every action', places: [S('audit')], look: 'Events table with filters; Chain tab verifies the hashes.' },
      { req: 'Consent management', places: [C('Citizen app /my-data')], look: 'Share, withdraw and correct, per purpose.' },
      { req: 'Mock identity, payment and data services', places: [S('mocks'), S('payments')], look: 'Mock controls and SMS log; payments appear only after an approved decision.' },
    ],
  },
  {
    id: 'pick3',
    title: 'The "pick at least 3" features',
    rows: [
      { req: 'Multi-tenant workspaces', places: [S('settings')], look: 'Top bar shows the department. Accounts with several memberships get a Switch menu. Data is separated by Postgres row-level security.' },
      { req: 'Admin rule editor', places: [S('rules')], look: 'Form builder and JSON view, validation, diff against the active version.' },
      { req: 'Notifications', places: [S('outbox')], look: 'The mock SMS and in-app messages that were sent, with delivery state.' },
      { req: 'Webhooks', places: [S('webhooks')], look: 'Endpoints, signed deliveries and their outcomes.' },
      { req: 'Analytics dashboard per tenant', places: [S('overview'), S('impact')], look: 'Overview for live numbers, Impact for routes, time and fraud.' },
      { req: 'Officer review queue (priority, confidence)', places: [S('queue')], look: 'Sort by priority, confidence or age.' },
      { req: 'Subscription plans and usage limits', places: [S('usage')], look: 'Metered this month against the plan; over-limit calls are refused with 429.' },
      { req: 'Background jobs and queues', places: [S('jobs')], look: 'Jobs table by status (Postgres queue, no Redis).' },
      { req: 'Rate limiting and error handling', places: [S('usage'), S('lab', 'Challenge Lab')], look: 'Limits per plan; Lab shows real error bodies with request ids.' },
      { req: 'Low-bandwidth or offline mode', places: [C('Citizen app /apply'), P('Feature-phone simulator', '/ussd')], look: 'Installable PWA; offline answers queue and sync.' },
    ],
  },
  {
    id: 'ai',
    title: 'AI features',
    rows: [
      { req: 'RAG with sources', places: [C('Citizen app /rules')], look: 'Ask about the rules; the answer cites the policy text it came from.' },
      { req: 'Agent with tool calling', places: [S('queue', 'Queue, case, Assistant tab')], look: 'Open a case, then the Assistant tab: the run and the mock tool calls it made.' },
      { req: 'Classification and routing', places: [S('scam-reports'), S('decisions')], look: 'Scam class with confidence; decisions route to auto, ask more or a person.' },
      { req: 'Computer vision on documents', places: [P('Test cards', '/demo/kit'), S('queue', 'Queue, case, Anatomy tab')], look: 'Try the altered and blurry cards in the app; staff see why a document was flagged.' },
      { req: 'Voice in Urdu', places: [C('Citizen app /apply')], look: 'Answer by voice; the system reads it back and waits for confirmation.' },
      { req: 'Structured outputs', places: [S('decisions')], look: 'Every decision is a typed record: facts, rules fired, probabilities, route.' },
      { req: 'Guardrails and human approval', places: [S('approvals'), S('queue')], look: 'Payments above the limit need a second officer; risky cases need a person.' },
      { req: 'Explainability', places: [S('decisions')], look: 'Rule trace for staff, grade-5 reason for the citizen.' },
      { req: 'Anomaly detection', places: [S('anomalies')], look: 'Repeated claims and unusual patterns, each with its signal.' },
      { req: 'Memory and context', places: [C('Citizen app /apply')], look: 'Leave and return: the form resumes where it stopped, on this phone.' },
      { req: 'Evaluation dashboard', places: [S('evals'), P('Live engine view', '/live')], look: 'Accuracy, false alarms and rule versions; /live draws the held-out cases.' },
    ],
  },
  {
    id: 'bonus',
    title: 'Bonus features',
    rows: [
      { req: 'Digital Twin', places: [S('twin')], look: 'Run a draft rule on past cases and see the change before publishing.' },
      { req: 'Helper Mode', places: [C('Citizen app /', 'Rubina (helper)')], look: 'The list of 40 families; each needs that family\'s PIN and consent.' },
      { req: 'Offline-first sync', places: [C('Citizen app /apply')], look: 'Answer offline, reconnect, and it syncs once without duplicates.' },
      { req: 'Scam Map', places: [S('scam-map')], look: 'Tile-grid map by area, type and time, from classified messages.' },
    ],
  },
  {
    id: 'demo',
    title: 'Demo pages',
    rows: [
      { req: 'One-tap sign-in and thresholds', places: [P('Demo page', '/demo')], look: 'Every demo account, with what each one is for.' },
      { req: 'Specimen ID cards for testing', places: [P('Test cards', '/demo/kit')], look: 'Download the clean, blurry, altered and other cards.' },
      { req: 'Feature-phone simulator', places: [P('USSD', '/ussd')], look: 'Dial the code and step through the menu.' },
      { req: 'Decision engine, drawn', places: [P('Live engine', '/live')], look: 'Held-out cases routed under the same cost matrix.' },
    ],
  },
];

const DEMO_ROLE_NAME: Record<StaffRole, string> = { officer: 'Officer Farhan Qureshi', admin: 'Admin Ayesha Siddiqui', auditor: 'Auditor Nadia Hussain' };

function rowText(r: Row): string {
  const places = r.places.map((p) => (p.kind === 'staff' ? (p.label ?? findNavItem(p.slug)?.label ?? p.slug) : p.label)).join(' ');
  return `${r.req} ${places} ${r.look}`.toLowerCase();
}

function PlaceLink({ place, role }: { place: Place; role: string }) {
  if (place.kind === 'staff') {
    const item = findNavItem(place.slug);
    if (!item) return null;
    const label = place.label ?? item.label;
    const open = item.roles === 'staff' || (item.roles as readonly string[]).includes(role);
    const first = item.roles === 'staff' ? undefined : item.roles[0];
    return (
      <span class="gd-place">
        <a href={`/staff/${item.slug}`} class="gd-link">
          {label}
        </a>
        {open ? null : <span class="gd-note">Sign in as {first ? DEMO_ROLE_NAME[first] : 'a staff user'} on /demo</span>}
      </span>
    );
  }
  if (place.kind === 'citizen') {
    return (
      <span class="gd-place">
        <a href="/" class="gd-link">
          {place.label}
        </a>
        <span class="gd-note">Needs a citizen sign-in{place.who === 'anyone' ? '' : `: ${place.who}`} on /demo</span>
      </span>
    );
  }
  return (
    <span class="gd-place">
      <a href={place.href} class="gd-link">
        {place.label}
      </a>
    </span>
  );
}

/** Staff guide at /staff/guide: where each requirement of the brief lives in the running app. */
export function GuidePage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = activeRole();
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const groups = useMemo(
    () => GROUPS.map((g) => ({ ...g, rows: needle ? g.rows.filter((r) => rowText(r).includes(needle)) : g.rows })).filter((g) => g.rows.length > 0),
    [needle],
  );
  const total = groups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <section aria-labelledby="page-title" class="gd flex max-w-5xl flex-col gap-3">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
            Where is what
          </h1>
          <p class="text-sm text-ink-muted">The brief, mapped to the running app. Each link opens the page that shows it.</p>
        </div>
        <label class="flex flex-col gap-1 text-xs text-ink-muted">
          Filter rows
          <input
            type="search"
            class={`${INPUT} w-64 max-w-full`}
            placeholder="rules, scam, consent, voice"
            value={q}
            onInput={(e) => setQ(e.currentTarget.value)}
            aria-controls="gd-body"
          />
        </label>
      </div>
      <nav aria-label="Guide sections" class="gd-chips">
        {GROUPS.map((g) => (
          <a key={g.id} href={`#gd-${g.id}`} class="gd-chip">
            {g.title}
          </a>
        ))}
      </nav>
      <div id="gd-body" aria-live="polite">
        {total === 0 ? (
          <p class="gd-empty">Nothing matches "{q}". Try a shorter word.</p>
        ) : (
          groups.map((g) => (
            <section key={g.id} id={`gd-${g.id}`} aria-labelledby={`gd-h-${g.id}`} class="gd-group">
              <h2 id={`gd-h-${g.id}`} class="gd-h">
                {g.title} <span class="gd-count">{g.rows.length}</span>
              </h2>
              <div class="gd-rows" role="table" aria-label={g.title}>
                <div class="gd-row gd-head" role="row">
                  <span role="columnheader">Requirement</span>
                  <span role="columnheader">Where</span>
                  <span role="columnheader">What to click or look for</span>
                </div>
                {g.rows.map((r) => (
                  <div key={r.req} class="gd-row" role="row">
                    <span class="gd-req" role="cell">
                      {r.req}
                    </span>
                    <span class="gd-where" role="cell">
                      {r.places.map((p, i) => (
                        <PlaceLink key={i} place={p} role={role} />
                      ))}
                    </span>
                    <span class="gd-look" role="cell">
                      {r.look}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </section>
  );
}
