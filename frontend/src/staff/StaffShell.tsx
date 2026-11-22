import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { logout, switchTenant } from '../shared/api/auth';
import type { ActiveMembership, AuthUser, Membership, Role } from '../shared/api/types';
import { Button } from '../shared/components/Button';
import { Emblem } from '../shared/components/Emblem';
import { PrototypeFooter } from '../shared/components/PrototypeFooter';
import { moreFor, railFor, type NavItem } from './nav';
import { NavIcon } from './NavIcons';
import { Palette } from './Palette';
import { prefetchPage } from './lazyPages';
import { PulseStrip } from './Pulse';
import { theme, toggleTheme } from './theme';

interface StaffShellProps {
  user: AuthUser;
  active: ActiveMembership;
  memberships: Membership[];
  children?: ComponentChildren;
}

const membershipKey = (m: { tenant_id: string; role: string }): string => `${m.tenant_id}|${m.role}`;

/** "More" grid groups: what you decide, what protects people, what proves it, what runs the system. */
const GROUPS: Array<{ title: string; slugs: readonly string[] }> = [
  { title: 'Command', slugs: ['overview', 'guide'] },
  { title: 'Decide', slugs: ['queue', 'approvals', 'payments', 'appeals', 'complaints', 'duplicates', 'decisions'] },
  { title: 'Protect', slugs: ['scam-map', 'scam-reports', 'mistakes', 'anomalies'] },
  { title: 'Prove', slugs: ['audit', 'costs', 'evals', 'twin', 'rules', 'impact', 'lab'] },
  { title: 'Operate', slugs: ['keys', 'users', 'webhooks', 'usage', 'jobs', 'mocks', 'outbox', 'health', 'settings'] },
];

function grouped(items: NavItem[]): Array<{ title: string; items: NavItem[] }> {
  const out = GROUPS.map((g) => ({ title: g.title, items: g.slugs.map((s) => items.find((i) => i.slug === s)).filter((i): i is NavItem => Boolean(i)) })).filter((g) => g.items.length > 0);
  const known = new Set(GROUPS.flatMap((g) => g.slugs));
  const rest = items.filter((i) => !known.has(i.slug));
  if (rest.length) out.push({ title: 'Other', items: rest });
  return out;
}

const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform);

/** Dense staff layout: night top bar, live pulse strip, grouped side navigation, command palette, content. */
export function StaffShell({ user, active, memberships, children }: StaffShellProps) {
  const { path, route } = useLocation();
  const pinned = railFor(active.role);
  const more = moreFor(active.role);
  const moreActive = more.some((i) => path === `/staff/${i.slug}` || path.startsWith(`/staff/${i.slug}/`));
  const [moreOpen, setMoreOpen] = useState(false);
  const moreBtn = useRef<HTMLButtonElement>(null);
  const morePanel = useRef<HTMLDivElement>(null);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [ctxOpen, setCtxOpen] = useState(false);
  const ctxBtn = useRef<HTMLButtonElement>(null);
  const ctxPanel = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    setMoreOpen(false);
    setCtxOpen(false);
  }, [path]);
  useEffect(() => {
    if (!ctxOpen) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!ctxPanel.current?.contains(t) && !ctxBtn.current?.contains(t)) setCtxOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setCtxOpen(false);
        ctxBtn.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [ctxOpen]);
  useEffect(() => setMoreOpen(false), [path]);
  useEffect(() => {
    if (!moreOpen) return;
    morePanel.current?.querySelector<HTMLElement>('a')?.focus();
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!morePanel.current?.contains(t) && !moreBtn.current?.contains(t)) setMoreOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMoreOpen(false);
        moreBtn.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [moreOpen]);

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

  return (
    <div class="st-frame flex min-h-dvh flex-col">
      <a
        href="#staff-main"
        class="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-paper focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header class="st-bar sb-row">
        <a href="/staff" class="sb-brand" aria-label="Rahat staff home">
          <span class="sb-brand-en">Rahat</span>
          <span class="font-urdu-hint sb-brand-ur" lang="ur" dir="rtl">راحت</span>
        </a>
        <div class="sb-ctx-wrap">
          <button
            ref={ctxBtn}
            type="button"
            class="sb-btn sb-ctx"
            aria-haspopup="dialog"
            aria-expanded={ctxOpen}
            aria-controls="sb-ctx-panel"
            title={`${active.tenant_name} (${active.tenant_slug}), ${active.role}`}
            onClick={() => setCtxOpen((v) => !v)}
          >
            <span class="sb-ctx-dept">{active.tenant_name}</span>
            <span class="sb-ctx-role">{active.role}</span>
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" class="sb-chev">
              <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          {ctxOpen ? (
            <div ref={ctxPanel} id="sb-ctx-panel" role="dialog" aria-label="Department, role and account" class="sb-pop">
              <dl class="sb-pop-list">
                <div>
                  <dt>Department</dt>
                  <dd>{active.tenant_name}</dd>
                </div>
                <div>
                  <dt>Role</dt>
                  <dd class="font-mono">{active.role}</dd>
                </div>
                <div class="sb-pop-account">
                  <dt>Signed in as</dt>
                  <dd>{user.display_name}</dd>
                </div>
              </dl>
              {memberships.length > 1 ? (
                <label class="sb-pop-switch">
                  <span>Switch department or role</span>
                  <select value={membershipKey(active)} disabled={switching} onChange={(event) => void onSwitch(event.currentTarget.value)}>
                    {memberships.map((m) => (
                      <option key={membershipKey(m)} value={membershipKey(m)}>
                        {m.tenant_name} / {m.role}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <button type="button" class="sb-btn sb-pop-out" disabled={leaving} onClick={() => void signOut()}>
                {leaving ? 'Signing out…' : 'Sign out'}
              </button>
            </div>
          ) : null}
        </div>
        <div class="sb-right">
          <button type="button" class="sb-btn sb-jump" onClick={() => setPaletteOpen(true)} aria-haspopup="dialog" aria-keyshortcuts="Control+K Meta+K" aria-label="Jump to a page">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
              <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
            <span class="sb-jump-text">Jump to</span>
            <kbd class="st-kbd sb-kbd">{isMac ? 'Cmd' : 'Ctrl'} K</kbd>
          </button>
          <button type="button" class="sb-btn sb-theme" onClick={(e) => toggleTheme(e)} aria-pressed={night} title="Switch between night and day" data-testid="theme-toggle">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              {night ? <path d="M13.5 9.6A5.8 5.8 0 0 1 6.4 2.5a5.8 5.8 0 1 0 7.1 7.1Z" /> : <><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" /></>}
            </svg>
            <span class="sb-theme-text">{night ? 'Night' : 'Day'}</span>
          </button>
          <span class="sb-name" title={user.display_name}>
            {user.display_name}
          </span>
          <button type="button" class="sb-btn sb-out" disabled={leaving} onClick={() => void signOut()}>
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
            {pinned.map((item) => {
              const href = `/staff/${item.slug}`;
              const current = path === href || path.startsWith(`${href}/`);
              return (
                <li key={item.slug}>
                  <a
                    href={href}
                    aria-label={item.label}
                    title={item.label}
                    aria-current={current ? 'page' : undefined}
                    class="nv-rail-link"
                    onPointerEnter={() => prefetchPage(item.slug)}
                    onFocus={() => prefetchPage(item.slug)}
                  >
                    <span class="nv-rail-icon">
                      <NavIcon slug={item.slug} />
                    </span>
                    <span class="nv-rail-label">{item.label}</span>
                  </a>
                </li>
              );
            })}
            {more.length > 0 ? (
              <li class="nv-rail-more">
                <button
                  ref={moreBtn}
                  type="button"
                  class={`nv-rail-link${moreActive ? ' is-here' : ''}`}
                  aria-label="More pages"
                  title="More pages"
                  aria-haspopup="dialog"
                  aria-expanded={moreOpen}
                  aria-controls="nv-more"
                  onClick={() => setMoreOpen((v) => !v)}
                >
                  <span class="nv-rail-icon">
                    <NavIcon slug="more" />
                  </span>
                  <span class="nv-rail-label">More</span>
                </button>
              </li>
            ) : null}
          </ul>
        </div>
      </nav>
      {moreOpen ? (
        <div ref={morePanel} id="nv-more" role="dialog" aria-label="All pages for your role" class="nv-more">
          {grouped(more).map((g) => (
            <section key={g.title} aria-label={g.title}>
              <h2 class="nv-more-h">{g.title}</h2>
              <ul class="nv-more-grid">
                {g.items.map((item) => {
                  const href = `/staff/${item.slug}`;
                  const current = path === href || path.startsWith(`${href}/`);
                  return (
                    <li key={item.slug}>
                      <a href={href} class="nv-more-item" aria-current={current ? 'page' : undefined} onPointerEnter={() => prefetchPage(item.slug)} onFocus={() => prefetchPage(item.slug)}>
                        <NavIcon slug={item.slug} />
                        <span>{item.label}</span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : null}
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
