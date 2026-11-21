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
  { slug: 'queue', label: 'Queue', roles: ['officer'], workItem: 'D2.2', built: true },
  { slug: 'rules', label: 'Rules', roles: ['admin'], workItem: 'D2.4', built: false },
  { slug: 'users', label: 'Users', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'keys', label: 'Keys', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'webhooks', label: 'Webhooks', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'jobs', label: 'Jobs', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'mocks', label: 'Mock services', roles: ['admin'], workItem: 'D2.11', built: false },
  { slug: 'audit', label: 'Audit', roles: ['auditor', 'admin'], workItem: 'D2.7', built: true },
  { slug: 'decisions', label: 'Decisions', roles: ['auditor'], workItem: 'D2.3', built: true },
  { slug: 'health', label: 'System health', roles: 'staff', workItem: 'D2.11', built: false },
];

/**
 * Build with VITE_SHOW_UNBUILT=false before the demo to hide every page that
 * is still a placeholder (CLAUDE.md: never leave a half-built screen reachable).
 */
export const SHOW_UNBUILT = import.meta.env.VITE_SHOW_UNBUILT !== 'false';

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
