import type { JSX } from 'preact';

/** One clean stroke icon per nav slug (24 px grid, currentColor). Drawn here; no icon package, no emoji. */
const P = (d: string): JSX.Element => <path d={d} />;
const ICONS: Record<string, JSX.Element> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1.6" />
      <rect x="14" y="3" width="7" height="5" rx="1.6" />
      <rect x="14" y="12" width="7" height="9" rx="1.6" />
      <rect x="3" y="16" width="7" height="5" rx="1.6" />
    </>
  ),
  queue: (
    <>
      {P('M9 6h12M9 12h12M9 18h12')}
      <circle cx="4.5" cy="6" r="1" />
      <circle cx="4.5" cy="12" r="1" />
      <circle cx="4.5" cy="18" r="1" />
    </>
  ),
  approvals: (
    <>
      <circle cx="12" cy="12" r="9" />
      {P('m8 12.5 3 3 5-6.5')}
    </>
  ),
  payments: (
    <>
      <rect x="2.5" y="5.5" width="19" height="13" rx="2.2" />
      {P('M2.5 10h19M6 15h4')}
    </>
  ),
  appeals: P('M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3'),
  complaints: P('M4 5h16v11H9l-5 4zM8 9.5h8M8 12.5h5'),
  rules: (
    <>
      {P('M4 7h9M19 7h1M4 17h1M11 17h9')}
      <circle cx="16" cy="7" r="2.2" />
      <circle cx="8" cy="17" r="2.2" />
    </>
  ),
  'scam-map': (
    <>
      {P('M12 21s7-6.2 7-11.5a7 7 0 0 0-14 0C5 14.8 12 21 12 21z')}
      <circle cx="12" cy="9.5" r="2.5" />
    </>
  ),
  'scam-reports': P('M5 21V4M5 4h12l-2 4 2 4H5'),
  mistakes: P('M12 3 2.5 20h19zM12 10v4.5M12 17.4v.1'),
  outbox: P('M3 13l2-8h14l2 8v6H3zM3 13h5l1 3h6l1-3h5'),
  users: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      {P('M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6M15.5 5.2a3 3 0 0 1 0 5.6M18 14.5c2 .6 3 2.3 3 5')}
    </>
  ),
  keys: (
    <>
      <circle cx="8" cy="15" r="4" />
      {P('m11 12 9-9M16 7l3 3M14 9l2 2')}
    </>
  ),
  webhooks: P('M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'),
  usage: P('M5 20v-8M12 20V5M19 20v-5M3 20h18'),
  jobs: (
    <>
      <circle cx="12" cy="12" r="9" />
      {P('M12 7v5l3 2')}
    </>
  ),
  mocks: P('M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3'),
  audit: P('M12 3 4 6v6c0 4.5 3.2 7.8 8 9 4.8-1.2 8-4.5 8-9V6zM8.5 12l2.5 2.5 4.5-5'),
  decisions: (
    <>
      <circle cx="6" cy="5" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="18" cy="12" r="2" />
      {P('M6 7v10M6 10c0 2 2 2 10 2')}
    </>
  ),
  duplicates: (
    <>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      {P('M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2')}
    </>
  ),
  costs: (
    <>
      <circle cx="12" cy="12" r="9" />
      {P('M14.5 9.2c-.5-.8-1.5-1.2-2.5-1.2-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1 0-2-.4-2.5-1.2M12 6v2M12 16v2')}
    </>
  ),
  evals: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  twin: (
    <>
      <circle cx="9" cy="12" r="6" />
      <circle cx="15" cy="12" r="6" />
    </>
  ),
  impact: P('M3 17l6-6 4 4 8-9M15 6h6v6'),
  anomalies: P('M2 12h5l3-8 4 16 3-8h5'),
  lab: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      {P('m7 9 3 3-3 3M12 15h5')}
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      {P('M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1')}
    </>
  ),
  health: P('M20.8 5.6a5 5 0 0 0-7.1 0L12 7.3l-1.7-1.7a5 5 0 0 0-7.1 7.1L12 21.5l8.8-8.8a5 5 0 0 0 0-7.1z'),
};

export function NavIcon({ slug }: { slug: string }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      {ICONS[slug] ?? <circle cx="12" cy="12" r="3" />}
    </svg>
  );
}
