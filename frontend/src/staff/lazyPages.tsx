import type { ComponentType } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { LinkButton } from '../shared/components/Button';
import { ScreenState } from '../shared/components/ScreenState';
import { online } from '../shared/network';

/**
 * One chunk per staff page (vite.config.ts names them staff-*). The shell and the first page render as soon as their
 * own chunk arrives; every other page loads on first visit, and `prefetchPage` warms it when its rail item is hovered
 * or focused. A loaded page is kept, so going back to it is synchronous.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loader = () => Promise<ComponentType<any>>;

const LOADERS: Record<string, Loader> = {
  guide: () => import('./pages/GuidePage').then((m) => m.GuidePage),
  overview: () => import('./pages/OverviewPage').then((m) => m.OverviewPage),
  queue: () => import('./pages/QueuePage').then((m) => m.QueuePage),
  audit: () => import('./pages/AuditPage').then((m) => m.AuditPage),
  decisions: () => import('./pages/DecisionList').then((m) => m.DecisionIndex),
  rules: () => import('./pages/RulesPage').then((m) => m.RulesPage),
  approvals: () => import('./pages/MoneyPages').then((m) => m.ApprovalsPage),
  payments: () => import('./pages/MoneyPages').then((m) => m.PaymentsPage),
  outbox: () => import('./pages/OutboxPage').then((m) => m.OutboxPage),
  jobs: () => import('./pages/AdminPages').then((m) => m.JobsPage),
  mocks: () => import('./pages/AdminPages').then((m) => m.MocksPage),
  'scam-map': () => import('./pages/ScamMapPage').then((m) => m.ScamMapPage),
  'scam-reports': () => import('./pages/ScamReportsPage').then((m) => m.ScamReportsPage),
  mistakes: () => import('./pages/MistakesPage').then((m) => m.MistakesPage),
  costs: () => import('./pages/CostPage').then((m) => m.CostPage),
  twin: () => import('./pages/TwinPage').then((m) => m.TwinPage),
  evals: () => import('./pages/EvalsPage').then((m) => m.EvalsPage),
  duplicates: () => import('./pages/DuplicatesPage').then((m) => m.DuplicatesPage),
  keys: () => import('./pages/KeysPage').then((m) => m.KeysPage),
  webhooks: () => import('./pages/WebhooksPage').then((m) => m.WebhooksPage),
  usage: () => import('./pages/UsagePage').then((m) => m.UsagePage),
  appeals: () => import('./pages/AppealsPage').then((m) => m.AppealsPage),
  complaints: () => import('./pages/ComplaintsPage').then((m) => m.ComplaintsPage),
  lab: () => import('./pages/LabPage').then((m) => m.LabPage),
  settings: () => import('./pages/SettingsPage').then((m) => m.SettingsPage),
  health: () => import('./pages/HealthPage').then((m) => m.HealthPage),
  impact: () => import('./pages/ImpactPage').then((m) => m.ImpactPage),
  anomalies: () => import('./pages/AnomaliesPage').then((m) => m.AnomaliesPage),
  case: () => import('./pages/CasePage').then((m) => m.CasePage),
  decision: () => import('./pages/DecisionPage').then((m) => m.DecisionPage),
  'agent-run': () => import('./pages/AgentRunPage').then((m) => m.AgentRunPage),
};

const loaded = new Map<string, ComponentType<never>>();
const inflight = new Map<string, Promise<ComponentType<never>>>();

function load(key: string): Promise<ComponentType<never>> {
  const done = loaded.get(key);
  if (done) return Promise.resolve(done);
  let p = inflight.get(key);
  if (!p) {
    const loader = LOADERS[key];
    if (!loader) return Promise.reject(new Error(`no page ${key}`));
    p = loader().then((c) => {
      loaded.set(key, c as ComponentType<never>);
      return c as ComponentType<never>;
    });
    p.catch(() => inflight.delete(key)); // a failed download can be retried
    inflight.set(key, p);
  }
  return p;
}

/** Warm a page's chunk (rail hover or focus). Failure is silent: the real visit shows the error state. */
export function prefetchPage(slug: string): void {
  if (loaded.has(slug) || !LOADERS[slug]) return;
  load(slug).catch(() => undefined);
}

/** Renders a staff page by key, with loading and failed states of its own so the shell never waits for it. */
export function LazyPage({ page, ...props }: { page: string } & Record<string, unknown>) {
  const [Comp, setComp] = useState<ComponentType<never> | null>(() => loaded.get(page) ?? null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setFailed(false);
    const have = loaded.get(page);
    if (have) {
      setComp(() => have);
      return undefined;
    }
    setComp(null);
    load(page).then(
      (c) => live && setComp(() => c),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [page, attempt]);
  if (failed) {
    return (
      <ScreenState kind={online.value ? 'error' : 'offline'} density="staff" onRetry={() => setAttempt((n) => n + 1)}>
        <LinkButton href="/staff" size="sm" variant="neutral">
          Back to the console
        </LinkButton>
      </ScreenState>
    );
  }
  if (!Comp) return <ScreenState kind="loading" density="staff" />;
  const C = Comp as unknown as ComponentType<Record<string, unknown>>;
  return <C {...props} />;
}

// A direct visit to /staff/<page> starts that page's chunk now, in parallel with the session check, instead of after it.
if (typeof location !== 'undefined') {
  const first = /^\/staff\/([a-z-]+)/.exec(location.pathname)?.[1];
  if (first) prefetchPage(first === 'cases' ? 'case' : first === 'decisions' && /^\/staff\/decisions\/./.test(location.pathname) ? 'decision' : first);
}
