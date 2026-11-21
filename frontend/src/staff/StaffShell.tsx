import type { ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { logout, switchTenant } from '../shared/api/auth';
import type { ActiveMembership, AuthUser, Membership, Role } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { navFor } from './nav';

interface StaffShellProps {
  user: AuthUser;
  active: ActiveMembership;
  memberships: Membership[];
  children?: ComponentChildren;
}

const membershipKey = (m: { tenant_id: string; role: string }): string => `${m.tenant_id}|${m.role}`;

/** Dense staff layout: compact top bar, role-based left nav, content area. */
export function StaffShell({ user, active, memberships, children }: StaffShellProps) {
  const { path, route } = useLocation();
  const items = navFor(active.role);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);

  const onSwitch = async (value: string): Promise<void> => {
    const target = memberships.find((m) => membershipKey(m) === value);
    if (!target) return;
    setSwitching(true);
    setSwitchError(null);
    const result = await switchTenant(target.tenant_id, target.role as Role);
    setSwitching(false);
    if (result.ok) {
      route('/staff', true); // the new role may not have the current page
      return;
    }
    const f = result.failure;
    setSwitchError(
      f.kind === 'forbidden'
        ? 'You do not have access to that tenant.'
        : f.kind === 'offline'
          ? 'No network. Tenant not switched.'
          : `Switch failed${f.status ? ` (${f.status})` : ''}.${f.problem ? ` request_id ${f.problem.request_id}` : ''}`,
    );
  };

  const signOut = async (): Promise<void> => {
    setLeaving(true);
    await logout();
    route('/staff/login', true);
  };

  return (
    <div class="flex min-h-dvh flex-col bg-paper text-sm text-ink">
      <a
        href="#staff-main"
        class="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-paper focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header class="flex flex-wrap items-center gap-x-4 gap-y-1 bg-chrome px-3 py-1.5 text-chrome-ink">
        <a href="/staff" class="font-semibold text-chrome-ink no-underline">
          Rahat staff
        </a>
        <span class="rounded-sm border border-chrome-muted px-1.5 font-mono text-xs uppercase tracking-wide text-chrome-muted">
          Prototype
        </span>
        <span class="text-chrome-muted" title={active.tenant_slug}>
          Tenant <span class="font-semibold text-chrome-ink">{active.tenant_name}</span>
        </span>
        <span class="text-chrome-muted">
          Role <span class="font-mono font-semibold text-chrome-ink">{active.role}</span>
        </span>
        {memberships.length > 1 ? (
          <label class="flex items-center gap-1.5 text-chrome-muted">
            Switch
            <select
              class="h-7 rounded-sm border border-chrome-muted bg-chrome px-1 text-chrome-ink"
              value={membershipKey(active)}
              disabled={switching}
              onChange={(event) => void onSwitch(event.currentTarget.value)}
            >
              {memberships.map((m) => (
                <option key={membershipKey(m)} value={membershipKey(m)}>
                  {m.tenant_name} / {m.role}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <span class="ms-auto text-chrome-muted">{user.display_name}</span>
        <button
          type="button"
          class="h-7 rounded-sm border border-chrome-muted px-2 text-chrome-ink hover:bg-ink disabled:opacity-70"
          disabled={leaving}
          onClick={() => void signOut()}
        >
          {leaving ? 'Signing out…' : 'Sign out'}
        </button>
      </header>
      {switchError ? (
        <p role="alert" class="border-b border-danger bg-danger-soft px-3 py-1 text-danger">
          {switchError}
        </p>
      ) : null}

      <div class="flex flex-1 flex-col md:flex-row">
        <nav aria-label="Staff" class="border-b border-line bg-sunken md:w-52 md:shrink-0 md:border-e md:border-b-0">
          <ul class="flex flex-wrap gap-0.5 p-2 md:flex-col">
            {items.map((item) => {
              const href = `/staff/${item.slug}`;
              const current = path === href || path.startsWith(`${href}/`);
              return (
                <li key={item.slug}>
                  <a
                    href={href}
                    aria-current={current ? 'page' : undefined}
                    class={
                      'flex items-center justify-between gap-2 rounded-sm px-2 py-1.5 no-underline ' +
                      (current ? 'bg-chrome text-chrome-ink' : 'text-ink hover:bg-surface')
                    }
                  >
                    <span>{item.label}</span>
                    {item.built ? null : (
                      <span class={`font-mono text-xs ${current ? 'text-chrome-muted' : 'text-ink-subtle'}`}>dev</span>
                    )}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
        <main id="staff-main" tabIndex={-1} class="min-w-0 flex-1 p-4">
          {children}
        </main>
      </div>
      <PrototypeFooter density="staff" />
    </div>
  );
}

/** Used by the shell's sign-out and by pages that need a compact action. */
export function StaffSignOutButton() {
  const { route } = useLocation();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="neutral"
      busy={busy}
      onClick={async () => {
        setBusy(true);
        await logout();
        route('/staff/login', true);
      }}
    >
      Sign out
    </Button>
  );
}
