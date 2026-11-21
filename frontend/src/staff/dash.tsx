import type { ComponentChildren } from 'preact';
import { useCallback, useEffect, useId, useRef, useState } from 'preact/hooks';
import type { ApiFailure, Result } from '../shared/api/problem';
import { toneOf, type Tone } from './charts';
import { failureText } from './kit';

/**
 * Building blocks for the Command Center: a quiet refresher, a panel body that shows every state, sparklines,
 * a donut and the hex-tile map. Hand-written SVG; no chart or map library, no map data, no tiles.
 */

export type Quiet<T> = { state: 'loading' } | { state: 'ok'; data: T; stale: boolean; at: number } | { state: 'fail'; failure: ApiFailure };

/** Loads on mount and every `ms` while the tab is visible. A failed refresh keeps the last good answer and marks it stale. */
export function useQuiet<T>(run: () => Promise<Result<T>>, ms: number): [Quiet<T>, () => void] {
  const [q, setQ] = useState<Quiet<T>>({ state: 'loading' });
  const last = useRef<{ data: T; at: number } | null>(null);
  const runRef = useRef(run);
  runRef.current = run;
  const alive = useRef(true);
  const load = useCallback(async () => {
    const res = await runRef.current();
    if (!alive.current) return;
    if (res.ok) {
      last.current = { data: res.data, at: Date.now() };
      setQ({ state: 'ok', data: res.data, stale: false, at: last.current.at });
    } else if (last.current && res.failure.kind !== 'forbidden') {
      setQ({ state: 'ok', data: last.current.data, stale: true, at: last.current.at });
    } else {
      setQ({ state: 'fail', failure: res.failure });
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    const id = window.setInterval(() => {
      if (!document.hidden) void load();
    }, ms);
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive.current = false;
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load, ms]);
  return [q, () => void load()];
}

/** Every state of a panel: skeleton while loading, plain words for 403, offline and errors, the content otherwise. */
export function QuietView<T>({
  q,
  reload,
  what,
  rows = 4,
  children,
}: {
  q: Quiet<T>;
  reload: () => void;
  /** What the panel shows, for the sentences that explain a refusal. */
  what: string;
  rows?: number;
  children: (data: T) => ComponentChildren;
}) {
  if (q.state === 'loading') {
    return (
      <div role="status" aria-label={`Loading ${what}`} class="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} class="rh-skeleton h-6" />
        ))}
      </div>
    );
  }
  if (q.state === 'fail') {
    const f = q.failure;
    if (f.kind === 'forbidden') {
      return (
        <p role="status" class="flex items-start gap-2 text-ink-muted">
          <span class="st-chip warn">403</span>
          <span>Your role cannot read {what}. Nothing is made up in its place.</span>
        </p>
      );
    }
    if (f.kind === 'offline' || f.kind === 'network') {
      return (
        <p role="status" class="flex flex-wrap items-center gap-2 text-ink-muted">
          <span class="st-chip warn">offline</span>
          <span>{f.kind === 'offline' ? 'You are offline.' : 'The server did not answer.'} This panel updates by itself when the connection returns.</span>
          <button type="button" class="st-chip info hover:brightness-125" onClick={reload}>
            Try now
          </button>
        </p>
      );
    }
    return (
      <p role="alert" class="flex flex-wrap items-center gap-2 text-danger">
        <span class="st-chip bad">error</span>
        <span>{failureText(f)}</span>
        {f.problem?.request_id ? <span class="font-mono text-xs text-ink-subtle">request_id {f.problem.request_id}</span> : null}
        <button type="button" class="st-chip info hover:brightness-125" onClick={reload}>
          Try again
        </button>
      </p>
    );
  }
  return (
    <>
      {q.stale ? (
        <p class="mb-1 text-xs text-warning-ink" role="status">
          Refresh failed; showing the answer from {new Date(q.at).toISOString().slice(11, 19)}Z.
        </p>
      ) : null}
      {children(q.data)}
    </>
  );
}

/** Counts of timestamps per bucket: hourly over the last 24 h when anything happened in that window, else daily over 7 d. */
export function bucketize(items: readonly { at: string; w?: number }[], now = Date.now()): { values: number[]; window: '24 h' | '7 d' } {
  const times = items.map((i) => ({ t: new Date(i.at).getTime(), w: i.w ?? 1 })).filter((i) => Number.isFinite(i.t));
  const H = 3_600_000;
  const recent = times.filter((i) => now - i.t < 24 * H && i.t <= now + H);
  const hourly = recent.length > 0;
  const size = hourly ? H : 24 * H;
  const n = hourly ? 24 : 7;
  const values = new Array<number>(n).fill(0);
  for (const i of hourly ? recent : times) {
    const age = Math.floor((now - i.t) / size);
    if (age >= 0 && age < n) values[n - 1 - age] = (values[n - 1 - age] ?? 0) + i.w;
  }
  return { values, window: hourly ? '24 h' : '7 d' };
}

/** A small line with a gradient area and a glowing last point. Text alternative says the range and the last value. */
export function Sparkline({ values, tone, label, w = 132, h = 38 }: { values: readonly number[]; tone: Tone; label: string; w?: number; h?: number }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const n = values.length;
  const max = Math.max(1, ...values);
  const x = (i: number) => 3 + (n <= 1 ? 0 : (i * (w - 6)) / (n - 1));
  const y = (v: number) => 4 + (h - 9) * (1 - v / max);
  if (n === 0) return null;
  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join('');
  const area = `${line}L${x(n - 1).toFixed(1)} ${h - 3}L${x(0).toFixed(1)} ${h - 3}Z`;
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} class={`st-chart st-tone-${tone} block max-w-full`} role="img" aria-label={`${label}: ${total} in total, last bucket ${values[n - 1]}`}>
      <defs>
        <linearGradient id={`${uid}-s`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" class="st-stop" stop-opacity="0.45" />
          <stop offset="1" class="st-stop" stop-opacity="0" />
        </linearGradient>
      </defs>
      <line x1="3" x2={w - 3} y1={h - 3} y2={h - 3} class="stroke-line" stroke-width="1" />
      {total > 0 ? <path d={area} fill={`url(#${uid}-s)`} class="st-area" /> : null}
      <path d={line} fill="none" class="st-spark st-line st-glow" pathLength={100} stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx={x(n - 1)} cy={y(values[n - 1] ?? 0)} r="5.5" class="st-halo" />
      <circle cx={x(n - 1)} cy={y(values[n - 1] ?? 0)} r="2.6" class="st-spark-dot st-pt" />
    </svg>
  );
}

export interface Seg {
  key: string;
  label: string;
  value: number;
  tone: Tone;
}

/** A donut with the total in the centre. Hover or focus a segment to read its share. */
export function Donut({ segs, centreLabel, id }: { segs: readonly Seg[]; centreLabel: string; id: string }) {
  const total = segs.reduce((a, s) => a + s.value, 0);
  const [sel, setSel] = useState<string | null>(null);
  const cur = segs.find((s) => s.key === sel);
  const R = 42;
  const C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <figure class="st-chart m-0 flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 120 120" class="block h-44 w-44 shrink-0" role="img" aria-labelledby={`${id}-d`}>
        <desc id={`${id}-d`}>{`Decision mix, ${total} decisions: ${segs.map((s) => `${s.label} ${s.value}`).join(', ')}.`}</desc>
        <circle cx="60" cy="60" r={R} fill="none" class="stroke-line" stroke-width="15" />
        {total > 0
          ? segs.map((s, i) => {
              const len = (s.value / total) * C;
              const off = acc;
              acc += len;
              if (s.value <= 0) return null;
              return (
                <g key={s.key} class={`st-tone-${s.tone}`} transform="rotate(-90 60 60)">
                  <circle
                    cx="60"
                    cy="60"
                    r={R}
                    fill="none"
                    class={`st-seg ${sel === s.key ? 'on' : ''} outline-none`}
                    stroke-width={sel === s.key ? 19 : 15}
                    stroke-dasharray={`${Math.max(0, len - 1.2)} ${C - Math.max(0, len - 1.2)}`}
                    stroke-dashoffset={-off}
                    style={{ animationDelay: `${i * 110}ms` }}
                    tabIndex={0}
                    role="img"
                    aria-label={`${s.label}: ${s.value} of ${total}, ${Math.round((s.value / total) * 100)} percent`}
                    onMouseEnter={() => setSel(s.key)}
                    onMouseLeave={() => setSel(null)}
                    onFocus={() => setSel(s.key)}
                    onBlur={() => setSel(null)}
                  />
                </g>
              );
            })
          : null}
        <text x="60" y={cur ? 57 : 62} text-anchor="middle" class="rh-num fill-ink text-[24px] font-black">
          {cur ? cur.value : total}
        </text>
        <text x="60" y={cur ? 72 : 77} text-anchor="middle" class="fill-ink-muted text-[8.5px] uppercase tracking-wider">
          {cur ? `${Math.round((cur.value / (total || 1)) * 100)}% ${cur.label}` : centreLabel}
        </text>
      </svg>
      <ul class="flex min-w-[10rem] flex-1 flex-col gap-1.5 text-sm">
        {segs.map((s) => (
          <li
            key={s.key}
            class={`st-legend st-tone-${s.tone} !rounded-md ${sel === s.key ? 'ring-1 ring-focus' : ''}`}
            onMouseEnter={() => setSel(s.key)}
            onMouseLeave={() => setSel(null)}
          >
            <span class="st-swatch" aria-hidden="true" />
            <span class="text-ink">{s.label}</span>
            <span class="ms-auto ps-3 font-mono font-bold tabular-nums text-ink">{s.value}</span>
            <span class="w-10 text-end font-mono text-xs tabular-nums">{total > 0 ? `${Math.round((s.value / total) * 100)}%` : 'n/a'}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}

/* ---------- Pakistan as hexagons ---------- */

export interface Province {
  key: string;
  name: string;
  short: string;
  /** Hex-grid position in hexagon widths. Odd rows are shifted half a hexagon. Rough geography, north at the top. */
  x: number;
  y: number;
}

export const PROVINCES: readonly Province[] = [
  { key: 'GB', name: 'Gilgit-Baltistan', short: 'GB', x: 2, y: 0 },
  { key: 'KP', name: 'Khyber Pakhtunkhwa', short: 'KP', x: 1.5, y: 1 },
  { key: 'AJK', name: 'Azad Kashmir', short: 'AJK', x: 2.5, y: 1 },
  { key: 'ICT', name: 'Islamabad', short: 'ICT', x: 2, y: 2 },
  { key: 'BAL', name: 'Balochistan', short: 'BAL', x: 1, y: 2 },
  { key: 'PB', name: 'Punjab', short: 'PB', x: 3, y: 2 },
  { key: 'SD', name: 'Sindh', short: 'SD', x: 2.5, y: 3 },
];

/** Districts outside the two provinces whose tile maps the system already has. Real geography, nothing about the data. */
const EXTRA_DISTRICTS: Record<string, string> = {
  Islamabad: 'ICT',
  Peshawar: 'KP',
  Abbottabad: 'KP',
  Mardan: 'KP',
  Swat: 'KP',
  Kohat: 'KP',
  Bannu: 'KP',
  'Dera Ismail Khan': 'KP',
  Quetta: 'BAL',
  Gwadar: 'BAL',
  Turbat: 'BAL',
  Khuzdar: 'BAL',
  Gilgit: 'GB',
  Skardu: 'GB',
  Muzaffarabad: 'AJK',
  Mirpur: 'AJK',
  Rawalakot: 'AJK',
};

export function provinceOf(district: string, sindh: ReadonlySet<string>, punjab: ReadonlySet<string>): string | null {
  if (sindh.has(district)) return 'SD';
  if (punjab.has(district)) return 'PB';
  return EXTRA_DISTRICTS[district] ?? null;
}

const HEX_R = 44;
const HEX_W = Math.sqrt(3) * HEX_R;
const OPAC = [0.18, 0.34, 0.52, 0.74, 0.95];

function hexPoints(cx: number, cy: number, r: number): string {
  return Array.from({ length: 6 }, (_, k) => {
    const a = (Math.PI / 180) * (60 * k - 30);
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(' ');
}

export interface HexRow {
  province: Province;
  count: number;
  top: readonly { district: string; count: number }[];
}

/** Seven hexagons laid out like the country. A province with no data in the system is drawn empty, never filled in. */
export function HexMap({ rows, unit }: { rows: readonly HexRow[]; unit: string }) {
  const [sel, setSel] = useState<string | null>(null);
  const max = Math.max(1, ...rows.map((r) => r.count));
  const minX = Math.min(...PROVINCES.map((p) => p.x));
  const cx = (p: Province) => (p.x - minX + 0.5) * HEX_W + 4;
  const cy = (p: Province) => p.y * HEX_R * 1.5 + HEX_R + 4;
  const w = (Math.max(...PROVINCES.map((p) => p.x)) - minX + 1) * HEX_W + 8;
  const h = Math.max(...PROVINCES.map((p) => p.y)) * HEX_R * 1.5 + HEX_R * 2 + 8;
  const cur = rows.find((r) => r.province.key === sel);
  return (
    <figure class="st-chart relative m-0">
      {cur ? (
        <div class="st-tip" style={{ left: '50%', top: '0.2rem', transform: 'translateX(-50%)' }} role="tooltip">
          <div class="font-semibold">{cur.province.name}</div>
          <div class="font-mono text-xs">{cur.count > 0 ? `${cur.count} ${unit}` : `no ${unit} in the data`}</div>
          {cur.top.slice(0, 3).map((d) => (
            <div key={d.district} class="flex gap-3 text-xs text-ink-muted">
              <span>{d.district}</span>
              <span class="ms-auto font-mono tabular-nums">{d.count}</span>
            </div>
          ))}
        </div>
      ) : null}
      <svg viewBox={`0 0 ${w} ${h}`} class="mx-auto block w-full max-w-[340px]" role="group" aria-label={`Hexagon map of Pakistan, ${unit} per province`}>
        <text x={w - 4} y="14" text-anchor="end" class="fill-ink-muted text-[11px] font-semibold">
          N
        </text>
        <path d={`M${w - 12} 20L${w - 12} 34M${w - 12} 20l-3 5M${w - 12} 20l3 5`} class="stroke-ink-muted" fill="none" stroke-width="1.2" />
        {rows.map((r, i) => {
          const p = r.province;
          const level = r.count <= 0 ? -1 : Math.min(4, Math.floor(((r.count - 1) / max) * 5));
          const x = cx(p);
          const y = cy(p);
          const on = sel === p.key;
          const label = r.count > 0 ? `${p.name}: ${r.count} ${unit}` : `${p.name}: no ${unit} in the data`;
          return (
            <g
              key={p.key}
              class="st-tone-bad st-hex outline-none"
              tabIndex={0}
              role="img"
              aria-label={label}
              style={{ animationDelay: `${i * 70}ms` }}
              onMouseEnter={() => setSel(p.key)}
              onMouseLeave={() => setSel(null)}
              onFocus={() => setSel(p.key)}
              onBlur={() => setSel(null)}
            >
              {r.count > 0 ? <polygon points={hexPoints(x, y, HEX_R - 2)} class="st-halo" /> : null}
              <polygon
                points={hexPoints(x, y, HEX_R - 4)}
                class={r.count > 0 ? 'st-hexfill' : 'fill-sunken stroke-line-strong'}
                fill-opacity={r.count > 0 ? OPAC[level] : undefined}
                stroke-width={on ? 3 : 1.5}
                stroke-dasharray={r.count > 0 ? undefined : '5 4'}
                stroke-linejoin="round"
              />
              <text x={x} y={y - 3} text-anchor="middle" class={`${level >= 3 ? 'fill-white' : 'fill-ink'} text-[13px] font-black`}>
                {p.short}
              </text>
              <text x={x} y={y + 15} text-anchor="middle" class={`${level >= 3 ? 'fill-white' : 'fill-ink-muted'} rh-num text-[10.5px] font-bold`}>
                {r.count > 0 ? r.count : 'no data'}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export function HexLegend({ max, unit }: { max: number; unit: string }) {
  const bounds = OPAC.map((_, i) => Math.max(1, Math.ceil(((i + 1) * max) / 5)));
  return (
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
      <svg width={OPAC.length * 38 + 4} height="30" role="img" aria-label={`Colour scale from few to many ${unit}`}>
        {bounds.map((b, i) => (
          <g key={b + '-' + i}>
            <rect x={2 + i * 38} y="2" width="36" height="12" rx="3" class="fill-danger" fill-opacity={OPAC[i]} />
            <text x={2 + i * 38 + 18} y="26" font-size="9.5" text-anchor="middle" class="fill-ink-muted">
              {i === 0 ? `1-${b}` : `${(bounds[i - 1] ?? 0) + 1}-${b}`}
            </text>
          </g>
        ))}
      </svg>
      <span class="inline-flex items-center gap-1.5">
        <svg width="18" height="16" aria-hidden="true">
          <polygon points={hexPoints(9, 8, 7)} fill="none" stroke="currentColor" stroke-dasharray="3 2" />
        </svg>
        empty: no {unit} in the data
      </span>
    </div>
  );
}

export { toneOf };
