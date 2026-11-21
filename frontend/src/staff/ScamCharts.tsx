import { useId, useState } from 'preact/hooks';
import { toneOf } from './charts';
import { shortDay, labelText, type TrendsOut } from './scam';

/** Hand-written SVG. No chart or map library (CLAUDE.md). Fills use classes and attributes only, so the strict CSP holds. */

const LEVELS = 5;
const LEVEL_OPACITY = [0.14, 0.32, 0.52, 0.76, 1];

export function levelFor(count: number, max: number): number {
  if (count <= 0 || max <= 0) return -1;
  return Math.min(LEVELS - 1, Math.floor(((count - 1) / max) * LEVELS));
}

/** Upper bound of each colour step, for the legend. */
export function levelBounds(max: number): number[] {
  return Array.from({ length: LEVELS }, (_, i) => Math.max(1, Math.ceil(((i + 1) * max) / LEVELS)));
}

const TILE_W = 86;
const TILE_H = 54;
const GAP = 4;

function splitName(name: string): [string, string] {
  if (name.length <= 12) return [name, ''];
  const words = name.split(' ');
  let first = words[0] ?? '';
  let i = 1;
  while (i < words.length - 1 && `${first} ${words[i]}`.length <= 12) first += ` ${words[i++]}`;
  const rest = words.slice(i).join(' ');
  return [first, rest.length > 14 ? `${rest.slice(0, 13)}.` : rest];
}

export interface TileGridProps {
  title: string;
  rows: readonly (readonly (string | null)[])[];
  counts: ReadonlyMap<string, number>;
  max: number;
  /** How many (district, type) groups the server hid. Zero means a missing count really is zero. */
  hiddenGroups: number;
  selected: string | null;
  onSelect: (district: string) => void;
  id: string;
}

export function TileGrid({ title, rows, counts, max, hiddenGroups, selected, onSelect, id }: TileGridProps) {
  const cols = Math.max(...rows.map((r) => r.length));
  const w = cols * (TILE_W + GAP) + GAP;
  const h = rows.length * (TILE_H + GAP) + GAP;
  return (
    <figure class="st-chart m-0">
      <figcaption class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">{title}</figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} class="block w-full max-w-[640px]" role="group" aria-label={`${title} district tiles`}>
        <defs>
          <pattern id={`${id}-hide`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" class="fill-sunken" />
            <line x1="0" y1="0" x2="0" y2="6" class="stroke-line-strong" stroke-width="1.5" />
          </pattern>
        </defs>
        {rows.flatMap((row, r) =>
          row.map((name, c) => {
            if (name === null) return null;
            const count = counts.get(name) ?? 0;
            const visible = count > 0;
            const hiddenTile = !visible && hiddenGroups > 0;
            const level = levelFor(count, max);
            const x = GAP + c * (TILE_W + GAP);
            const y = GAP + r * (TILE_H + GAP);
            const [l1, l2] = splitName(name);
            const dark = level >= 3;
            const label = visible ? `${name}: ${count} reports` : hiddenTile ? `${name}: fewer than 5 reports, hidden` : `${name}: no reports`;
            return (
              <g
                key={name}
                role="button"
                tabIndex={0}
                aria-label={label}
                aria-pressed={selected === name}
                class="cursor-pointer outline-none [&:focus-visible>rect:last-of-type]:stroke-focus"
                onClick={() => onSelect(name)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(name);
                  }
                }}
              >
                <title>{label}</title>
                {visible ? (
                  <rect x={x} y={y} width={TILE_W} height={TILE_H} class="fill-danger st-pt" style={{ animationDelay: `${(r * 6 + c) * 25}ms` }} fill-opacity={LEVEL_OPACITY[level]} />
                ) : (
                  <rect x={x} y={y} width={TILE_W} height={TILE_H} fill={hiddenTile ? `url(#${id}-hide)` : undefined} class={hiddenTile ? '' : 'fill-sunken'} />
                )}
                <rect
                  x={x}
                  y={y}
                  width={TILE_W}
                  height={TILE_H}
                  fill="none"
                  class={selected === name ? 'stroke-ink' : 'stroke-line-strong'}
                  stroke-width={selected === name ? 3 : 1}
                />
                <text x={x + 5} y={y + 13} font-size="10" class={dark ? 'fill-white' : 'fill-ink'}>
                  {l1}
                </text>
                {l2 ? (
                  <text x={x + 5} y={y + 24} font-size="10" class={dark ? 'fill-white' : 'fill-ink'}>
                    {l2}
                  </text>
                ) : null}
                <text x={x + TILE_W - 5} y={y + TILE_H - 7} font-size={visible ? 17 : 12} font-weight="700" text-anchor="end" class={dark ? 'fill-white' : 'fill-ink'}>
                  {visible ? count : hiddenTile ? '<5' : '0'}
                </text>
              </g>
            );
          }),
        )}
      </svg>
    </figure>
  );
}

export function TileLegend({ max, hiddenGroups }: { max: number; hiddenGroups: number }) {
  const bounds = levelBounds(max);
  const sw = 40;
  return (
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
      <svg width={LEVELS * sw + 4} height="30" role="img" aria-label="Colour scale from few to many reports">
        {bounds.map((b, i) => (
          <g key={i}>
            <rect x={2 + i * sw} y="2" width={sw - 2} height="12" class="fill-danger stroke-line-strong" fill-opacity={LEVEL_OPACITY[i]} />
            <text x={2 + i * sw + (sw - 2) / 2} y="26" font-size="9" text-anchor="middle" class="fill-ink-muted">
              {i === 0 ? `1-${b}` : `${(bounds[i - 1] ?? 0) + 1}-${b}`}
            </text>
          </g>
        ))}
      </svg>
      <span class="inline-flex items-center gap-1">
        <svg width="18" height="14" aria-hidden="true">
          <defs>
            <pattern id="legend-hide" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" class="fill-sunken" />
              <line x1="0" y1="0" x2="0" y2="6" class="stroke-line-strong" stroke-width="1.5" />
            </pattern>
          </defs>
          <rect x="1" y="1" width="16" height="12" fill="url(#legend-hide)" class="stroke-line-strong" />
        </svg>
        {hiddenGroups > 0 ? '<5 = fewer than 5 reports, hidden to protect people' : 'none hidden in this view'}
      </span>
    </div>
  );
}

/* ---------- trend lines ---------- */

const SERIES_STYLE: Record<string, { cls: string; dash?: string }> = {
  relief_scam: { cls: 'stroke-danger' },
  phishing_link: { cls: 'stroke-info', dash: '6 3' },
  advance_fee: { cls: 'stroke-warning-ink', dash: '2 3' },
  impersonation: { cls: 'stroke-primary', dash: '9 3 2 3' },
  legit_program_message: { cls: 'stroke-ink-muted', dash: '1 3' },
  unknown: { cls: 'stroke-line-strong', dash: '4 4' },
};
const styleFor = (label: string) => SERIES_STYLE[label] ?? { cls: 'stroke-ink' };

export function TrendChart({ trends, only }: { trends: TrendsOut; only: string | null }) {
  const series = trends.series.filter((s) => only === null || s.label === only);
  const days = series[0]?.points.map((p) => p.day) ?? trends.total.map((p) => p.day);
  const n = days.length;
  const max = Math.max(5, ...series.flatMap((s) => s.points.map((p) => p.count ?? 0)));
  const W = 560;
  const H = 210;
  const L = 34;
  const R = 8;
  const T = 10;
  const B = 28;
  const x = (i: number) => L + (n <= 1 ? 0 : (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, Math.round(max / 2), max];
  const every = Math.max(1, Math.ceil(n / 7));
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [hi, setHi] = useState<number | null>(null);
  const move = (clientX: number, el: SVGElement) => {
    const svg = el.ownerSVGElement ?? (el as SVGSVGElement);
    const rect = svg.getBoundingClientRect();
    const mx = ((clientX - rect.left) / rect.width) * W;
    setHi(n === 0 ? null : Math.max(0, Math.min(n - 1, Math.round(((mx - L) / (W - L - R)) * (n - 1)))));
  };
  const hiRows = hi === null ? [] : series.map((s) => ({ label: s.label, count: s.points[hi]?.count ?? null }));
  return (
    <figure class="st-chart relative m-0 flex flex-col gap-1">
      {hi !== null ? (
        <div class="st-tip" style={{ left: `${Math.min(80, Math.max(20, (x(hi) / W) * 100))}%`, top: '0', transform: 'translateX(-50%)' }} role="tooltip">
          <div class="font-mono text-[11px] text-ink-muted">{days[hi]}</div>
          {hiRows.map((r) => (
            <div key={r.label} class="flex items-center gap-1.5">
              <span class={`st-swatch st-tone-${toneOf(styleFor(r.label).cls)}`} aria-hidden="true" />
              <span>{labelText(r.label)}</span>
              <span class="ms-auto ps-3 font-mono font-bold tabular-nums">{r.count === null ? 'hidden (<5)' : r.count}</span>
            </div>
          ))}
        </div>
      ) : null}
      <svg viewBox={`0 0 ${W} ${H}`} class="block w-full" role="img" aria-label={`Reports per day by type over the last ${trends.days} days`}>
        <defs>
          {series.map((s, i) => (
            <linearGradient key={s.label} id={`${uid}-g${i}`} x1="0" y1="0" x2="0" y2="1" class={`st-tone-${toneOf(styleFor(s.label).cls)}`}>
              <stop offset="0" class="st-stop" stop-opacity="0.34" />
              <stop offset="1" class="st-stop" stop-opacity="0" />
            </linearGradient>
          ))}
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} class="stroke-line" stroke-width="1" />
            <text x={L - 4} y={y(t) + 3} font-size="10" text-anchor="end" class="fill-ink-muted">
              {t}
            </text>
          </g>
        ))}
        {days.map((d, i) =>
          i % every === 0 || i === n - 1 ? (
            <text key={d} x={x(i)} y={H - 10} font-size="10" text-anchor={i === n - 1 ? 'end' : i === 0 ? 'start' : 'middle'} class="fill-ink-muted">
              {shortDay(d)}
            </text>
          ) : null,
        )}
        {series.map((s, si) => {
          const st = styleFor(s.label);
          const runs: string[] = [];
          let cur: string[] = [];
          s.points.forEach((p, i) => {
            if (p.count === null || p.count === undefined) {
              if (cur.length) runs.push(cur.join(' '));
              cur = [];
            } else cur.push(`${x(i).toFixed(1)},${y(p.count).toFixed(1)}`);
          });
          if (cur.length) runs.push(cur.join(' '));
          return (
            <g key={s.label}>
              {runs.map((pts, k) =>
                pts.includes(' ') && !st.dash ? (
                  <polygon key={`a${k}`} points={`${pts} ${pts.split(' ').slice(-1)[0]!.split(',')[0]},${y(0)} ${pts.split(' ')[0]!.split(',')[0]},${y(0)}`} fill={`url(#${uid}-g${si})`} class="st-area" />
                ) : null,
              )}
              {runs.map((pts, k) =>
                pts.includes(' ') ? (
                  <polyline key={k} points={pts} fill="none" class={`${st.cls} ${st.dash ? 'st-fade' : 'st-line st-glow'}`} pathLength={st.dash ? undefined : 100} stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray={st.dash} />
                ) : (
                  <circle key={k} cx={pts.split(',')[0]} cy={pts.split(',')[1]} r="2.5" class={`${st.cls} fill-paper`} stroke-width="2" />
                ),
              )}
              {s.points.map((p, i) =>
                p.count === null || p.count === undefined ? (
                  <rect key={p.day} x={x(i) - 3} y={y(0) - 3} width="6" height="6" class={`${st.cls} fill-paper`} stroke-width="1.5">
                    <title>{`${labelText(s.label)} ${p.day}: fewer than 5, hidden`}</title>
                  </rect>
                ) : null,
              )}
            </g>
          );
        })}
        {hi !== null ? (
          <g pointer-events="none">
            <line x1={x(hi)} x2={x(hi)} y1={T} y2={H - B} class="stroke-ink-muted" stroke-width="1" stroke-dasharray="2 3" />
            {hiRows.map((r) =>
              r.count === null ? null : (
                <g key={r.label} class={`st-tone-${toneOf(styleFor(r.label).cls)}`}>
                  <circle cx={x(hi)} cy={y(r.count)} r="8" class="st-halo" />
                  <circle cx={x(hi)} cy={y(r.count)} r="4" class="st-dotfill" stroke-width="2" />
                </g>
              ),
            )}
          </g>
        ) : null}
        <rect
          x={L}
          y={T}
          width={W - L - R}
          height={H - T - B}
          fill="transparent"
          class="cursor-crosshair outline-none [&:focus-visible]:stroke-focus"
          stroke-width="2"
          tabIndex={0}
          role="application"
          aria-label="Reports per day. Use the left and right arrow keys to read each day."
          onMouseMove={(e) => move(e.clientX, e.currentTarget)}
          onMouseLeave={() => setHi(null)}
          onTouchMove={(e) => e.touches[0] && move(e.touches[0].clientX, e.currentTarget)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight') setHi((v) => Math.min(n - 1, (v ?? -1) + 1));
            else if (e.key === 'ArrowLeft') setHi((v) => Math.max(0, (v ?? 1) - 1));
            else if (e.key === 'Escape') setHi(null);
            else return;
            e.preventDefault();
          }}
          onBlur={() => setHi(null)}
        />
      </svg>
      <figcaption class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        {series.map((s) => {
          const st = styleFor(s.label);
          return (
            <span key={s.label} class="inline-flex items-center gap-1">
              <svg width="26" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="26" y2="4" class={st.cls} stroke-width="2" stroke-dasharray={st.dash} />
              </svg>
              {labelText(s.label)}
            </span>
          );
        })}
        <span class="inline-flex items-center gap-1">
          <svg width="10" height="10" aria-hidden="true">
            <rect x="1.5" y="1.5" width="7" height="7" class="fill-paper stroke-ink-muted" stroke-width="1.5" />
          </svg>
          hollow square on the baseline = fewer than 5 that day, hidden
        </span>
      </figcaption>
    </figure>
  );
}

export function Spark({ points }: { points: { day: string; count: number | null }[] }) {
  const n = points.length;
  const max = Math.max(5, ...points.map((p) => p.count ?? 0));
  const W = 120;
  const H = 26;
  const x = (i: number) => 2 + (n <= 1 ? 0 : (i * (W - 4)) / (n - 1));
  const y = (v: number) => 2 + (H - 6) * (1 - v / max);
  const runs: string[] = [];
  let cur: string[] = [];
  points.forEach((p, i) => {
    if (p.count === null) {
      if (cur.length) runs.push(cur.join(' '));
      cur = [];
    } else cur.push(`${x(i).toFixed(1)},${y(p.count).toFixed(1)}`);
  });
  if (cur.length) runs.push(cur.join(' '));
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily reports, ${n} days`}>
      <line x1="2" x2={W - 2} y1={H - 3} y2={H - 3} class="stroke-line" />
      {runs.map((pts, k) => (pts.includes(' ') ? <polyline key={k} points={pts} fill="none" class="stroke-danger" stroke-width="1.5" /> : null))}
      {points.map((p, i) => (p.count === null ? <rect key={p.day} x={x(i) - 1.5} y={H - 5} width="3" height="3" class="fill-ink-muted" /> : null))}
    </svg>
  );
}
