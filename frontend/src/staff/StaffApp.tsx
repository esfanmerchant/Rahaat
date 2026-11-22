import type { ComponentChildren } from 'preact';
import { Route, Router, useLocation } from 'preact-iso';
import { homePathFor, isStaffRole, session } from '../shared/api/auth';
import { ErrorBoundary } from '../shared/components/ErrorBoundary';
import { LinkButton } from '../shared/components/Button';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { ScreenState } from '../shared/components/ScreenState';
import { useTemporaryLang } from '../shared/i18n';
import { Redirect } from '../shared/routing';
import { findNavItem, navFor, type NavItem } from './nav';
import { PlaceholderPage } from './PlaceholderPage';
import { LazyPage } from './lazyPages';
import { StaffLogin } from './StaffLogin';
import { StaffShell, StaffSignOutButton } from './StaffShell';
import { StaffRoot } from './theme';

/**
 * Staff console, lazy-loaded at /staff and /staff/*. Its code never ships in
 * the citizen bundle. English and LTR while mounted.
 */
export default function StaffApp() {
  useTemporaryLang('en');
  return (
    <StaffRoot>
    <ErrorBoundary density="staff">
      <Router>
        <Route path="/login" component={StaffLoginRoute} />
        <Route path="/" component={StaffIndex} />
        <Route path="/cases/:id" component={CaseRoute} />
        <Route path="/decisions/:id" component={DecisionRoute} />
        <Route path="/agent-runs/:id" component={AgentRunRoute} />
        <Route path="/:section" component={StaffSection} />
        <Route default component={StaffNotFound} />
      </Router>
    </ErrorBoundary>
    </StaffRoot>
  );
}

function Bare({ children }: { children?: ComponentChildren }) {
  return (
    <div class="flex min-h-dvh flex-col">
      <main class="mx-auto w-full max-w-3xl flex-1 p-4">{children}</main>
      <PrototypeFooter density="staff" />
    </div>
  );
}

/**
 * Staff guard. Signed out: go to /staff/login. Signed in with a citizen or
 * helper role: permission denied (the server would refuse every staff call anyway).
 */
function StaffGuard({ children }: { children: (s: Extract<typeof session.value, { status: 'signed-in' }>) => ComponentChildren }) {
  const current = session.value;
  if (current.status === 'restoring') {
    return (
      <Bare>
        <ScreenState kind="loading" density="staff" />
      </Bare>
    );
  }
  if (current.status === 'signed-out') return <Redirect to="/staff/login" />;
  if (!isStaffRole(current.active.role)) {
    return (
      <Bare>
        <ScreenState
          kind="denied"
          density="staff"
          title="Staff only"
          body={`You are signed in as ${current.active.role}. The staff console needs an officer, admin or auditor account.`}
        >
          <LinkButton href="/" size="sm" variant="neutral">
            Go to the citizen app
          </LinkButton>
          <StaffSignOutButton />
        </ScreenState>
      </Bare>
    );
  }
  return <>{children(current)}</>;
}

/** After a successful sign-in this guard routes by role: staff to /staff, citizen and helper to /. */
function StaffLoginRoute() {
  const current = session.value;
  if (current.status === 'signed-in') return <Redirect to={homePathFor(current.active.role)} />;
  return <StaffLogin />;
}

function StaffIndex() {
  return (
    <StaffGuard>
      {(s) => {
        const pages = navFor(s.active.role);
        const first = pages.find((p) => p.slug === 'overview') ?? pages[0];
        return first ? (
          <Redirect to={`/staff/${first.slug}`} />
        ) : (
          <StaffShell user={s.user} active={s.active} memberships={s.memberships}>
            <ScreenState kind="empty" density="staff" title="No pages for this role yet" body="Nothing is built for this role." />
          </StaffShell>
        );
      }}
    </StaffGuard>
  );
}

function StaffSection({ section }: { section?: string }) {
  return (
    <StaffGuard>
      {(s) => {
        const item = findNavItem(section ?? '');
        const allowed = item !== undefined && navFor(s.active.role).some((entry) => entry.slug === item.slug);
        return (
          <StaffShell user={s.user} active={s.active} memberships={s.memberships}>
            {item === undefined ? (
              <ScreenState kind="not_found" density="staff" title="Page not found" body="There is no staff page at this address." />
            ) : allowed ? (
              <SectionPage item={item} />
            ) : (
              <ScreenState
                kind="denied"
                density="staff"
                title="Not available for your role"
                body={`${item.label} is not part of the ${s.active.role} console. The server enforces this too.`}
              />
            )}
          </StaffShell>
        );
      }}
    </StaffGuard>
  );
}

function SectionPage({ item }: { item: NavItem }) {
  if (item.slug === 'twin') return <TwinRoute />;
  if (!NAV_BUILT.has(item.slug)) return <PlaceholderPage item={item} />;
  return <LazyPage page={item.slug} />;
}

const NAV_BUILT = new Set(
  'guide overview queue audit decisions rules approvals payments outbox jobs mocks scam-map scam-reports mistakes costs twin evals duplicates keys webhooks usage appeals complaints lab settings health impact anomalies'.split(' '),
);

/** A deep link that the role's nav does not list: same guard, explicit role list. */
function RoleRoute({ roles, label, children }: { roles: readonly string[]; label: string; children: () => ComponentChildren }) {
  return (
    <StaffGuard>
      {(s) => (
        <StaffShell user={s.user} active={s.active} memberships={s.memberships}>
          {roles.includes(s.active.role) ? (
            children()
          ) : (
            <ScreenState kind="denied" density="staff" title="Not available for your role" body={`${label} is for ${roles.join(' and ')} accounts. The server enforces this too.`} />
          )}
        </StaffShell>
      )}
    </StaffGuard>
  );
}

function CaseRoute({ id }: { id?: string }) {
  return (
    <RoleRoute roles={['officer']} label="Case review">
      {() => <LazyPage page="case" id={id ?? ''} />}
    </RoleRoute>
  );
}

function AgentRunRoute({ id }: { id?: string }) {
  return (
    <RoleRoute roles={['officer', 'admin', 'auditor']} label="The assistant run">
      {() => <LazyPage page="agent-run" id={id ?? ''} />}
    </RoleRoute>
  );
}

function DecisionRoute({ id }: { id?: string }) {
  return (
    <RoleRoute roles={['auditor', 'officer']} label="The decision viewer">
      {() => <LazyPage page="decision" id={id ?? ''} />}
    </RoleRoute>
  );
}

function StaffNotFound() {
  return (
    <StaffGuard>
      {(s) => (
        <StaffShell user={s.user} active={s.active} memberships={s.memberships}>
          <ScreenState kind="not_found" density="staff" title="Page not found" body="There is no staff page at this address." />
        </StaffShell>
      )}
    </StaffGuard>
  );
}

function TwinRoute() {
  const { query } = useLocation();
  return <LazyPage page="twin" initialDraft={query['draft']} />;
}
