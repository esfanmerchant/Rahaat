import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { logout, switchTenant } from '../shared/api/auth';
import type { ActiveMembership, AuthUser, Membership, Role } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Emblem } from '../shared/components/Emblem';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { navFor, type NavItem } from './nav';
import { NavIcon } from './NavIcons';
import { Palette } from './Palette';
import { PulseStrip } from './Pulse';
import { theme, toggleTheme } from './theme';

interface StaffShellProps {
  user: AuthUser;
  active: ActiveMembership;
  memberships: Membership[];
  children?: ComponentChildren;
}

const membershipKey = (m: { tenant_id: string; role: string }): string => `${m.tenant_id}|${m.role}`;

/** Side navigation groups: what you decide, what protects people, what proves it, what runs the system. */
const GROUPS: Array<{ title: string; slugs: readonly string[] }> = [
  { title: 'Command', slugs: ['overview'] },
  { title: 'Decide', slugs: ['queue', 'approvals', 'payments', 'appeals', 'complaints', 'duplicates', 'decisions'] },
  { title: 'Protect', slugs: ['scam-map', 'scam-reports', 'mistakes', 'anomalies'] },
  { title: 'Prove', slugs: ['audit', 'costs', 'evals', 'twin', 'rules', 'impact', 'lab'] },
  { title: 'Operate', slugs: ['keys', 'users', 'webhooks', 'usage', 'jobs', 'mocks', 'outbox', 'health', 'settings'] },
];

function grouped(items: NavItem[]): Array<{ title: string; items: NavItem[] }> {
  const out = GROUPS.map((g) => ({ title: g.title, items: g.slugs.map((s) => items.find((i) => i.slug === s)).filter((i): i is NavItem => Boolean(i)) })).filter((g) => g.items.length > 0);
  const known = new Set(GROUPS.flatMap((g) => g.slugs));
  const rest = items.filter((i) => !known.has(i.slug));
  if (rest.length) out.push({ title: 'More', items: rest });
  return out;
}

const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform);

/** Dense staff layout: night top bar, live pulse strip, grouped side navigation, command palette, content. */
export function StaffShell({ user, active, memberships, children }: StaffShellProps) {
  const { path, route } = useLocation();
  const items = navFor(active.role);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const railRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

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

  const night = theme.value === 'night';
  const BTN_BAR = 'h-7 rounded-md border border-night-line px-2 text-night-ink hover:bg-night-3 disabled:opacity-70';

  return (
    <div class="st-frame flex min-h-dvh flex-col">
      <a
        href="#staff-main"
        class="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-paper focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header class="st-bar flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5">
        <a href="/staff" class="flex items-center gap-2 no-underline" aria-label="Rahat staff home">
          <span class="text-base font-black tracking-tight">Rahat</span>
          <span class="font-urdu-hint text-base" lang="ur" dir="rtl">راحت</span>
        </a>
        <span class="rounded-full border border-night-line px-2 font-mono text-xs uppercase tracking-wide text-night-muted">Prototype</span>
        <span class="st-bar-muted" title={active.tenant_slug}>
          Department <span class="font-semibold text-night-ink">{active.tenant_name}</span>
        </span>
        <span class="st-bar-muted">
          Role <span class="rounded-full bg-night-3 px-2 py-0.5 font-mono text-xs font-semibold text-noor">{active.role}</span>
        </span>
        {memberships.length > 1 ? (
          <label class="st-bar-muted flex items-center gap-1.5">
            Switch
            <select
              class="h-7 rounded-md border border-night-line bg-night px-1 text-night-ink"
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
        <div class="ms-auto flex items-center gap-2">
          <button type="button" class={`${BTN_BAR} flex items-center gap-2 text-night-muted`} onClick={() => setPaletteOpen(true)} aria-haspopup="dialog" aria-keyshortcuts="Control+K Meta+K">
            <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
            Jump to
            <kbd class="st-kbd">{isMac ? 'Cmd' : 'Ctrl'} K</kbd>
          </button>
          <button type="button" class={BTN_BAR} onClick={(e) => toggleTheme(e)} aria-pressed={night} title="Switch between night and day" data-testid="theme-toggle">
            {night ? 'Night' : 'Day'}
          </button>
          <span class="st-bar-muted" title={user.display_name}>
            {user.display_name}
          </span>
          <button type="button" class={BTN_BAR} disabled={leaving} onClick={() => void signOut()}>
            {leaving ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </header>
      <PulseStrip />
      {switchError ? (
        <p role="alert" class="border-b border-danger bg-danger-soft px-3 py-1 text-danger">
          {switchError}
        </p>
      ) : null}

      <nav
        ref={railRef}
        aria-label="Staff"
        class={`nv-rail${railOpen ? ' is-open' : ''}`}
        onPointerEnter={(e) => e.pointerType !== 'touch' && setRailOpen(true)}
        onPointerLeave={() => setRailOpen(false)}
        onFocusIn={(e) => (e.target as HTMLElement).matches(':focus-visible') && setRailOpen(true)}
        onFocusOut={(e) => !railRef.current?.contains(e.relatedTarget as Node | null) && setRailOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setRailOpen(false);
        }}
      >
        <div class="nv-rail-panel">
          <a href="/staff" class="nv-rail-logo" aria-label="Rahat staff home">
            <Emblem size={26} tone="night" animate />
            <span class="nv-rail-label">Rahat</span>
          </a>
          <ul class="nv-rail-list">
            {grouped(items).map((g) => (
              <li key={g.title} class="nv-rail-group" role="presentation">
                <p class="nv-rail-sep" aria-hidden="true">
                  <span>{g.title}</span>
                </p>
                <ul>
                  {g.items.map((item) => {
                    const href = `/staff/${item.slug}`;
                    const current = path === href || path.startsWith(`${href}/`);
                    return (
                      <li key={item.slug}>
                        <a href={href} aria-label={item.label} title={item.label} aria-current={current ? 'page' : undefined} class="nv-rail-link">
                          <span class="nv-rail-icon">
                            <NavIcon slug={item.slug} />
                          </span>
                          <span class="nv-rail-label">{item.label}</span>
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      </nav>
      <main id="staff-main" tabIndex={-1} class="min-w-0 flex-1 p-4">
        <div key={path} class="st-page-in">
          {children}
        </div>
      </main>
      <PrototypeFooter density="staff" />
      <Palette role={active.role} open={paletteOpen} onClose={() => setPaletteOpen(false)} onSignOut={() => void signOut()} />
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
