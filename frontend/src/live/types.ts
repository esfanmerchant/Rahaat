import type { paths } from '../shared/api/schema';

/** The public pulse (GET /v1/public/pulse), as the generated client types it. */
export type Pulse = paths['/v1/public/pulse']['get']['responses'][200]['content']['application/json'];
export type ReplayCase = Pulse['replay']['cases'][number];
export type Headline = NonNullable<Pulse['replay']['headline']>;

/** The four paths a case can take through the cost-matrix gate. A hard-rule rejection is route auto with outcome rejected. */
export type Lane = 'approve' | 'ask' | 'human' | 'reject';

export function laneOf(c: Pick<ReplayCase, 'route' | 'outcome'>): Lane {
  if (c.route === 'ask_more') return 'ask';
  if (c.route === 'human') return 'human';
  return c.outcome === 'rejected' ? 'reject' : 'approve';
}

/** Noor palette (shared/tokens.css), as 0xRRGGBB numbers for WebGL and hex strings for SVG and HTML. */
export const LANE_COLOR: Record<Lane, string> = {
  approve: '#4ee6a6', // emerald-glow
  ask: '#f2a51e', // saffron
  human: '#8ea2ff', // indigo-glow
  reject: '#ff6b81', // madder-glow
};
export const NOOR = '#ffd36e';
export const SHIELD_COLOR = '#ff6b81';

export const LANE_LABEL: Record<Lane, string> = {
  approve: 'Approved automatically',
  ask: 'Asked for proof',
  human: 'A person will check',
  reject: 'Hard-rule rejection',
};

export interface Capability {
  ok: boolean;
  reason: 'webgl-unavailable' | 'reduced-motion' | 'save-data' | null;
}

/** WebGL only when it works and neither reduced motion nor Save-Data is on. Never downloads three.js to find out. */
export function detectCapability(): Capability {
  try {
    const params = new URLSearchParams(window.location.search);
    const forced = params.get('view');
    if (forced === 'static') return { ok: false, reason: 'reduced-motion' };
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return { ok: false, reason: 'reduced-motion' };
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (connection?.saveData === true) return { ok: false, reason: 'save-data' };
    const probe = document.createElement('canvas');
    const gl = probe.getContext('webgl2') ?? probe.getContext('webgl');
    if (!gl) return { ok: false, reason: 'webgl-unavailable' };
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    return { ok: false, reason: 'webgl-unavailable' };
  }
  return { ok: true, reason: null };
}
