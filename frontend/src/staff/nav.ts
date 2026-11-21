/**
 * Staff navigation, generated from the active role. This is a convenience
 * only: the server enforces every permission, and every page handles 403.
 */
export type StaffRole = 'officer' | 'admin' | 'auditor';

export interface NavItem {
  slug: string;
  label: string;
  /** Roles that see this item. 'staff' means every staff role. */
  roles: readonly StaffRole[] | 'staff';
  /** PLAN work item that builds the page. */
  workItem: string;
  /** Flip to true when the page is real. Unbuilt pages are dev placeholders. */
  built: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { slug: 'guide', label: 'Guide', roles: 'staff', workItem: 'D2.14', built: true },
  { slug: 'overview', label: 'Overview', roles: 'staff', workItem: 'D2.13', built: true },
  { slug: 'queue', label: 'Queue', roles: ['officer'], workItem: 'D2.2', built: true },
  { slug: 'approvals', label: 'Approvals', roles: ['officer'], workItem: 'D2.9', built: true },
  { slug: 'payments', label: 'Payments', roles: ['officer'], workItem: 'D2.9', built: true },
  { slug: 'appeals', label: 'Appeals', roles: ['officer', 'auditor'], workItem: 'WP-A', built: true },
  { slug: 'complaints', label: 'Complaints', roles: ['officer'], workItem: 'WP-A', built: true },
  { slug: 'rules', label: 'Rules', roles: ['admin'], workItem: 'D2.4', built: true },
  { slug: 'scam-map', label: 'Scam Map', roles: ['officer', 'admin'], workItem: 'D2.12', built: true },
  { slug: 'scam-reports', label: 'Scam reports', roles: 'staff', workItem: 'D2.12', built: true },
  { slug: 'mistakes', label: 'Mistakes', roles: 'staff', workItem: 'D2.12', built: true },
  { slug: 'outbox', label: 'Outbox', roles: ['officer', 'admin'], workItem: 'D2.9', built: true },
  { slug: 'users', label: 'Users', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'keys', label: 'API keys', roles: ['admin'], workItem: 'D2.11', built: true },
  { slug: 'webhooks', label: 'Webhooks', roles: ['admin'], workItem: 'WP-A', built: true },
  { slug: 'usage', label: 'Usage and plan', roles: ['admin'], workItem: 'WP-A', built: true },
  { slug: 'jobs', label: 'Jobs', roles: ['admin'], workItem: 'D2.11', built: true },
  { slug: 'mocks', label: 'Mock services', roles: ['admin'], workItem: 'D2.11', built: true },
  { slug: 'audit', label: 'Audit', roles: ['auditor', 'admin'], workItem: 'D2.7', built: true },
  { slug: 'decisions', label: 'Decisions', roles: ['auditor', 'officer'], workItem: 'D2.3', built: true },
  { slug: 'duplicates', label: 'Duplicates', roles: ['officer'], workItem: 'D2.6', built: true },
  { slug: 'costs', label: 'Cost of being wrong', roles: ['admin', 'auditor'], workItem: 'D2.5', built: true },
  { slug: 'twin', label: 'Digital Twin', roles: ['admin', 'auditor'], workItem: 'D2.5', built: true },
  { slug: 'evals', label: 'Evaluation', roles: ['admin', 'auditor'], workItem: 'D2.5', built: true },
  { slug: 'impact', label: 'Impact', roles: ['admin', 'officer'], workItem: 'B14', built: true },
  { slug: 'anomalies', label: 'Anomalies', roles: ['admin', 'officer', 'auditor'], workItem: 'B15', built: true },
  { slug: 'lab', label: 'Challenge Lab', roles: 'staff', workItem: 'D2.8', built: true },
  { slug: 'settings', label: 'Settings', roles: 'staff', workItem: 'D2.12', built: true },
  { slug: 'health', label: 'System health', roles: 'staff', workItem: 'D2.11', built: true },
];

/**
 * Placeholder pages show only on the dev server (CLAUDE.md: never leave a half-built screen reachable).
 * Every production build hides them, wherever it is deployed; VITE_SHOW_UNBUILT=true shows them in a build on purpose.
 */
export const SHOW_UNBUILT = import.meta.env.DEV ? import.meta.env.VITE_SHOW_UNBUILT !== 'false' : import.meta.env.VITE_SHOW_UNBUILT === 'true';

export function isStaffNavRole(role: string): role is StaffRole {
  return role === 'officer' || role === 'admin' || role === 'auditor';
}

export function navFor(role: string): NavItem[] {
  if (!isStaffNavRole(role)) return [];
  return NAV_ITEMS.filter(
    (item) => (SHOW_UNBUILT || item.built) && (item.roles === 'staff' || item.roles.includes(role)),
  );
}

export function findNavItem(slug: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.slug === slug);
}

/**
 * The pages pinned in the rail for each role (the ones that matter most). Everything else the role may open is
 * behind "More". Findability only: navFor() and the server decide what a role can actually open.
 */
export const RAIL_PINNED: Record<StaffRole, readonly string[]> = {
  officer: ['guide', 'overview', 'queue', 'approvals', 'decisions', 'scam-map', 'impact'],
  admin: ['guide', 'overview', 'rules', 'twin', 'mocks', 'keys', 'usage'],
  auditor: ['guide', 'overview', 'audit', 'decisions', 'evals', 'costs'],
};

/** The rail's pinned items for a role, in order, limited to pages the role can open. */
export function railFor(role: string): NavItem[] {
  if (!isStaffNavRole(role)) return [];
  const all = navFor(role);
  return RAIL_PINNED[role].map((slug) => all.find((i) => i.slug === slug)).filter((i): i is NavItem => Boolean(i));
}

/** Every other page the role may open: the "More" grid. */
export function moreFor(role: string): NavItem[] {
  const pinned = new Set(railFor(role).map((i) => i.slug));
  return navFor(role).filter((i) => !pinned.has(i.slug));
}
