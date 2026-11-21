import type { ComponentChildren } from 'preact';
import { useId, useState } from 'preact/hooks';

/**
 * Hand-written SVG charts for the evaluation pages. No chart library (CLAUDE.md).
 * Colours are classes (the strict CSP has no inline style attribute in markup), and every chart has a text alternative.
 *
 * Noor v2: gradient areas under lines, glowing points, a crosshair tooltip with exact values (mouse, touch and
 * arrow keys), threshold annotations as labelled pills, an animated draw-in, and legend chips. Reduced motion
 * keeps only fades (staff.css). Everything is sized to stay readable on a projector.
 */

const W = 460;
const H = 280;
const M = { l: 46, r: 14, t: 14, b: 38 };

export type Pt = readonly [number, number];
export type Tone = 'ok' | 'info' | 'warn' | 'bad' | 'muted';
export interface Series {
  name: string;
  points: readonly Pt[];
  /** Tailwind stroke class, from the tokens only. */
  stroke: string;
  dashed?: boolean;
  step?: boolean;
  /** Gradient area under the line. On by default for solid series. */
  area?: boolean;
}
export interface VLine {
  x: number;
  label: string;
  stroke: string;
  /** Row for the label so two labels do not overlap. */
  row?: number;
}
export interface HLine {
  y: number;
  label: string;
  stroke: string;
}
export interface Dot {
  x: number;
  y: number;
  label: string;
  fill: string;
}

/** The tone a stroke or fill class stands for, so gradients and glows follow the series colour. */
export function toneOf(cls: string): Tone {
  if (/primary|emerald|success|ok/.test(cls)) return 'ok';
  if (/warning|saffron|warn/.test(cls)) return 'warn';
  if (/danger|madder|bad/.test(cls)) return 'bad';
  if (/info|indigo/.test(cls)) return 'info';
  return 'muted';
}

function ticks(lo: number, hi: number, n = 5): number[] {
  const out: number[] = [];
  for (let i = 0; i <= n; i++) out.push(lo + ((hi - lo) * i) / n);
  return out;
}

const fmtTick = (v: number): string => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
const fmtExact = (v: number): string => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3));

export interface XYProps {
  id: string;
  title: string;
  xLabel: string;
  yLabel: string;
  series: readonly Series[];
  xDomain: Pt;
  yDomain: Pt;
  vlines?: readonly VLine[];
  hlines?: readonly HLine[];
  dots?: readonly Dot[];
  diagonal?: boolean;
  /** One sentence for screen readers and for people who do not see the picture. */
  summary: string;
}

interface Hover {
  px: number;
  rows: { name: string; tone: Tone; x: number; y: number }[];
}

export function XYChart({ id, title, xLabel, yLabel, series, xDomain, yDomain, vlines = [], hlines = [], dots = [], diagonal, summary }: XYProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [hover, setHover] = useState<Hover | null>(null);
  const [x0, x1] = xDomain;
  const [y0, y1] = yDomain;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0 || 1)) * (H - M.t - M.b);
  const clampX = (v: number) => Math.max(M.l, Math.min(W - M.r, v));
  const clampY = (v: number) => Math.max(M.t, Math.min(H - M.b, v));
  const sorted = series.map((s) => ({ s, pts: [...s.points].sort((a, b) => a[0] - b[0]) }));
  const path = (s: Series, pts: readonly Pt[]) => {
    if (pts.length === 0) return '';
    let d = `M${sx(pts[0]![0]).toFixed(1)} ${sy(pts[0]![1]).toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const p = pts[i]!;
      if (s.step) d += `H${sx(p[0]).toFixed(1)}V${sy(p[1]).toFixed(1)}`;
      else d += `L${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`;
    }
    return d;
  };
  const areaPath = (s: Series, pts: readonly Pt[]) => {
    if (pts.length < 2) return '';
    const base = sy(y0 <= 0 && y1 >= 0 ? 0 : y0);
    return `${path(s, pts)}L${sx(pts[pts.length - 1]![0]).toFixed(1)} ${base.toFixed(1)}L${sx(pts[0]![0]).toFixed(1)} ${base.toFixed(1)}Z`;
  };

  /** Nearest point of every series to a pixel x inside the plot. */
  const at = (mx: number): Hover | null => {
    if (sorted.every((e) => e.pts.length === 0)) return null;
    const dataX = x0 + ((mx - M.l) / (W - M.l - M.r)) * (x1 - x0);
    const rows = sorted
      .filter((e) => e.pts.length > 0)
      .map((e) => {
        const p = e.pts.reduce((m, q) => (Math.abs(q[0] - dataX) < Math.abs(m[0] - dataX) ? q : m), e.pts[0]!);
        return { name: e.s.name, tone: toneOf(e.s.stroke), x: p[0], y: p[1] };
      });
    const lead = rows.reduce((m, r) => (Math.abs(r.x - dataX) < Math.abs(m.x - dataX) ? r : m), rows[0]!);
    return { px: sx(lead.x), rows };
  };
  const onMove = (e: { clientX: number; currentTarget: Element }) => {
    const svg = (e.currentTarget as SVGElement).ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * W;
    setHover(mx < M.l || mx > W - M.r ? null : at(mx));
  };
  const onKey = (e: KeyboardEvent) => {
    const xs = [...new Set(sorted.flatMap((s) => s.pts.map((p) => p[0])))].sort((a, b) => a - b);
    if (xs.length === 0) return;
    const cur = hover ? hover.rows[0]!.x : undefined;
    let i = cur === undefined ? -1 : xs.findIndex((v) => v === cur);
    if (e.key === 'ArrowRight') i = Math.min(xs.length - 1, i + 1);
    else if (e.key === 'ArrowLeft') i = Math.max(0, i < 0 ? 0 : i - 1);
    else if (e.key === 'Escape') return setHover(null);
    else return;
    e.preventDefault();
    setHover(at(sx(xs[i]!)));
  };
  const tipLeft = hover ? Math.min(78, Math.max(22, (hover.px / W) * 100)) : 0;
  return (
    <figure class="st-chart relative m-0">
      <figcaption id={`${id}-t`} class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        {title}
      </figcaption>
      {hover ? (
        <div class="st-tip" style={{ left: `${tipLeft}%`, top: '1.6rem', transform: 'translateX(-50%)' }} role="tooltip" data-testid={`${id}-tip`}>
          <div class="font-mono text-[11px] text-ink-muted">
            {xLabel} {fmtExact(hover.rows[0]!.x)}
          </div>
          {hover.rows.map((r) => (
            <div key={r.name} class="flex items-center gap-1.5">
              <span class={`st-swatch st-tone-${r.tone}`} aria-hidden="true" />
              <span>{r.name}</span>
              <span class="ms-auto ps-3 font-mono font-bold tabular-nums">{fmtExact(r.y)}</span>
            </div>
          ))}
        </div>
      ) : null}
      <svg viewBox={`0 0 ${W} ${H}`} class="block w-full max-w-[760px]" role="img" aria-labelledby={`${id}-t ${id}-d`}>
        <desc id={`${id}-d`}>{summary}</desc>
        <defs>
          {sorted.map(({ s }, i) => (
            <linearGradient key={s.name} id={`${uid}-g${i}`} x1="0" y1="0" x2="0" y2="1" class={`st-tone-${toneOf(s.stroke)}`}>
              <stop offset="0" class="st-stop" stop-opacity="0.42" />
              <stop offset="1" class="st-stop" stop-opacity="0" />
            </linearGradient>
          ))}
        </defs>
        {ticks(y0, y1).map((t) => (
          <g key={`y${t}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} class="stroke-line" stroke-width="1" />
            <text x={M.l - 5} y={sy(t) + 3.5} text-anchor="end" class="fill-ink-muted text-[11px]">
              {fmtTick(t)}
            </text>
          </g>
        ))}
        {ticks(x0, x1).map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={H - M.b} y2={H - M.b + 4} class="stroke-line-strong" stroke-width="1" />
            <text x={sx(t)} y={H - M.b + 16} text-anchor="middle" class="fill-ink-muted text-[11px]">
              {fmtTick(t)}
            </text>
          </g>
        ))}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="none" class="stroke-line-strong" stroke-width="1" />
        {diagonal ? <line x1={sx(x0)} y1={sy(y0)} x2={sx(x1)} y2={sy(y1)} class="stroke-ink-subtle" stroke-width="1" stroke-dasharray="4 3" /> : null}
        {sorted.map(({ s, pts }, i) =>
          (s.area ?? !s.dashed) && pts.length > 1 ? <path key={`a${s.name}`} d={areaPath(s, pts)} fill={`url(#${uid}-g${i})`} class="st-area" /> : null,
        )}
        {hlines.map((h) => {
          const y = clampY(sy(h.y));
          const wpx = h.label.length * 5.6 + 8;
          return (
            <g key={h.label} class={`st-tone-${toneOf(h.stroke)}`}>
              <line x1={M.l} x2={W - M.r} y1={y} y2={y} class={h.stroke} stroke-width="1.5" stroke-dasharray="5 3" />
              <rect x={M.l + 4} y={y + 3} width={wpx} height="13" rx="6.5" class="st-pill" />
              <text x={M.l + 8} y={y + 12.5} text-anchor="start" class="fill-ink text-[10.5px] font-semibold">
                {h.label}
              </text>
            </g>
          );
        })}
        {vlines.map((v) => {
          const x = clampX(sx(v.x));
          const flip = sx(v.x) > W - 150;
          const row = v.row ?? 0;
          const wpx = v.label.length * 5.6 + 8;
          return (
            <g key={v.label} class={`st-tone-${toneOf(v.stroke)}`}>
              <line x1={x} x2={x} y1={M.t} y2={H - M.b} class={`${v.stroke} st-glow-line`} stroke-width="1.5" stroke-dasharray="5 3" />
              <rect x={flip ? x - wpx - 3 : x + 3} y={M.t + 2 + row * 16} width={wpx} height="13" rx="6.5" class="st-pill" />
              <text x={flip ? x - 7 : x + 7} y={M.t + 11.5 + row * 16} text-anchor={flip ? 'end' : 'start'} class="fill-ink text-[10.5px] font-semibold">
                {v.label}
              </text>
            </g>
          );
        })}
        {sorted.map(({ s, pts }) => (
          <g key={s.name} class={`st-tone-${toneOf(s.stroke)}`}>
            <path
              d={path(s, pts)}
              fill="none"
              class={`${s.stroke} ${s.dashed ? 'st-fade' : 'st-line st-glow'}`}
              pathLength={s.dashed ? undefined : 100}
              stroke-width="2.5"
              stroke-linejoin="round"
              stroke-linecap="round"
              stroke-dasharray={s.dashed ? '6 3' : undefined}
            />
          </g>
        ))}
        {dots.map((d) => (
          <g key={d.label} class={`st-tone-${toneOf(d.fill)}`}>
            <circle cx={sx(d.x)} cy={sy(d.y)} r="9" class="st-halo" />
            <circle cx={sx(d.x)} cy={sy(d.y)} r="5" class={`${d.fill} st-pt`} stroke-width="1.75">
              <title>{d.label}</title>
            </circle>
          </g>
        ))}
        {hover ? (
          <g pointer-events="none">
            <line x1={hover.px} x2={hover.px} y1={M.t} y2={H - M.b} class="stroke-ink-muted" stroke-width="1" stroke-dasharray="2 3" />
            {hover.rows.map((r) => (
              <g key={r.name} class={`st-tone-${r.tone}`}>
                <circle cx={sx(r.x)} cy={clampY(sy(r.y))} r="9" class="st-halo" />
                <circle cx={sx(r.x)} cy={clampY(sy(r.y))} r="4.5" class="st-dotfill" stroke-width="2" />
              </g>
            ))}
          </g>
        ) : null}
        <rect
          x={M.l}
          y={M.t}
          width={W - M.l - M.r}
          height={H - M.t - M.b}
          fill="transparent"
          class="cursor-crosshair outline-none [&:focus-visible]:stroke-focus"
          stroke-width="2"
          tabIndex={0}
          role="application"
          aria-label={`${title}. Use the left and right arrow keys to read exact values.`}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          onTouchMove={(e) => e.touches[0] && onMove({ clientX: e.touches[0].clientX, currentTarget: e.currentTarget })}
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
        />
        <text x={(M.l + W - M.r) / 2} y={H - 4} text-anchor="middle" class="fill-ink text-[12px]">
          {xLabel}
        </text>
        <text transform={`translate(11 ${(M.t + H - M.b) / 2}) rotate(-90)`} text-anchor="middle" class="fill-ink text-[12px]">
          {yLabel}
        </text>
      </svg>
      <p class="mt-1.5 flex flex-wrap gap-1.5 text-xs">
        {series.map((s) => (
          <span key={s.name} class={`st-legend st-tone-${toneOf(s.stroke)}`}>
            <svg width="18" height="8" class="inline" aria-hidden="true">
              <line x1="0" x2="18" y1="4" y2="4" class={s.stroke} stroke-width="2.5" stroke-linecap="round" stroke-dasharray={s.dashed ? '5 3' : undefined} />
            </svg>
            {s.name}
          </span>
        ))}
        {vlines.map((v) => (
          <span key={v.label} class={`st-legend st-tone-${toneOf(v.stroke)}`}>
            <svg width="14" height="10" class="inline" aria-hidden="true">
              <line x1="7" x2="7" y1="0" y2="10" class={v.stroke} stroke-width="2" stroke-dasharray="3 2" />
            </svg>
            {v.label}
          </span>
        ))}
        {hlines.map((h) => (
          <span key={h.label} class={`st-legend st-tone-${toneOf(h.stroke)}`}>
            <svg width="14" height="10" class="inline" aria-hidden="true">
              <line x1="0" x2="14" y1="5" y2="5" class={h.stroke} stroke-width="2" stroke-dasharray="3 2" />
            </svg>
            {h.label}
          </span>
        ))}
        {dots.map((d) => (
          <span key={d.label} class={`st-legend st-tone-${toneOf(d.fill)}`}>
            <svg width="10" height="10" class="inline" aria-hidden="true">
              <circle cx="5" cy="5" r="4" class={d.fill} stroke-width="1.5" />
            </svg>
            {d.label}
          </span>
        ))}
      </p>
    </figure>
  );
}

export interface BinIn {
  count: number;
  mean_predicted?: number | null;
  observed_rate?: number | null;
}

/** Reliability diagram: the dots should sit on the diagonal. The dot area follows how many cases fell in the bin. */
export function ReliabilityChart({ id, bins, ece, brier, n, marks = [] }: { id: string; bins: readonly BinIn[]; ece: number; brier: number; n: number; marks?: readonly VLine[] }) {
  const [sel, setSel] = useState<number | null>(null);
  const used = bins.filter((b) => b.count > 0 && b.mean_predicted != null && b.observed_rate != null);
  const maxCount = Math.max(1, ...used.map((b) => b.count));
  const sx = (v: number) => M.l + v * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - v * (H - M.t - M.b);
  const cur = sel !== null ? used[sel] : undefined;
  const label = (b: BinIn) => `${b.count} cases: said ${(b.mean_predicted as number).toFixed(2)}, happened ${(b.observed_rate as number).toFixed(2)}`;
  return (
    <figure class="st-chart relative m-0">
      <figcaption id={`${id}-t`} class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        Reliability: said versus happened
      </figcaption>
      {cur ? (
        <div class="st-tip" style={{ left: `${Math.min(78, Math.max(22, (sx(cur.mean_predicted as number) / W) * 100))}%`, top: '1.6rem', transform: 'translateX(-50%)' }} role="tooltip">
          <div class="font-mono text-[11px] text-ink-muted">{cur.count} cases in this bin</div>
          <div class="flex gap-3">
            <span>Said</span>
            <span class="ms-auto font-mono font-bold tabular-nums">{(cur.mean_predicted as number).toFixed(3)}</span>
          </div>
          <div class="flex gap-3">
            <span>Happened</span>
            <span class="ms-auto font-mono font-bold tabular-nums">{(cur.observed_rate as number).toFixed(3)}</span>
          </div>
        </div>
      ) : null}
      <svg viewBox={`0 0 ${W} ${H}`} class="block w-full max-w-[760px]" role="img" aria-labelledby={`${id}-t ${id}-d`}>
        <desc id={`${id}-d`}>{`Calibration on ${n} cases. Expected calibration error ${ece.toFixed(3)}, Brier score ${brier.toFixed(3)}. ${used.length} bins have cases.`}</desc>
        <defs>
          <linearGradient id={`${id}-band`} x1="0" y1="1" x2="1" y2="0" class="st-tone-ok">
            <stop offset="0" class="st-stop" stop-opacity="0" />
            <stop offset="1" class="st-stop" stop-opacity="0.2" />
          </linearGradient>
        </defs>
        {ticks(0, 1).map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} class="stroke-line" stroke-width="1" />
            <text x={M.l - 5} y={sy(t) + 3.5} text-anchor="end" class="fill-ink-muted text-[11px]">
              {t.toFixed(1)}
            </text>
            <text x={sx(t)} y={H - M.b + 16} text-anchor="middle" class="fill-ink-muted text-[11px]">
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="none" class="stroke-line-strong" stroke-width="1" />
        <path d={`M${sx(0)} ${sy(0)}L${sx(1)} ${sy(1)}L${sx(1)} ${sy(0)}Z`} fill={`url(#${id}-band)`} class="st-area" />
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} class="stroke-ink-subtle" stroke-width="1" stroke-dasharray="4 3" />
        {marks.map((v) => {
          const x = sx(Math.max(0, Math.min(1, v.x)));
          const wpx = v.label.length * 5.6 + 8;
          const flip = x > W - 150;
          const row = v.row ?? 0;
          return (
            <g key={v.label} class={`st-tone-${toneOf(v.stroke)}`}>
              <line x1={x} x2={x} y1={M.t} y2={H - M.b} class={`${v.stroke} st-glow-line`} stroke-width="1.5" stroke-dasharray="5 3" />
              <rect x={flip ? x - wpx - 3 : x + 3} y={H - M.b - 18 - row * 16} width={wpx} height="13" rx="6.5" class="st-pill" />
              <text x={flip ? x - 7 : x + 7} y={H - M.b - 8.5 - row * 16} text-anchor={flip ? 'end' : 'start'} class="fill-ink text-[10.5px] font-semibold">
                {v.label}
              </text>
            </g>
          );
        })}
        {used.map((b, i) => {
          const r = 4 + 7 * Math.sqrt(b.count / maxCount);
          return (
            <g key={`${b.mean_predicted}`} class="st-tone-info">
              <circle cx={sx(b.mean_predicted as number)} cy={sy(b.observed_rate as number)} r={r + 5} class="st-halo" />
              <circle
                cx={sx(b.mean_predicted as number)}
                cy={sy(b.observed_rate as number)}
                r={r}
                class="fill-info-soft stroke-info-strong st-pt outline-none [&:focus-visible]:stroke-focus"
                stroke-width="2"
                tabIndex={0}
                role="img"
                aria-label={label(b)}
                onMouseEnter={() => setSel(i)}
                onMouseLeave={() => setSel(null)}
                onFocus={() => setSel(i)}
                onBlur={() => setSel(null)}
              >
                <title>{label(b)}</title>
              </circle>
            </g>
          );
        })}
        <text x={(M.l + W - M.r) / 2} y={H - 4} text-anchor="middle" class="fill-ink text-[12px]">
          What the model said (mean p_ok in the bin)
        </text>
        <text transform={`translate(11 ${(M.t + H - M.b) / 2}) rotate(-90)`} text-anchor="middle" class="fill-ink text-[12px]">
          What happened (share truly OK)
        </text>
        <text x={M.l + 8} y={M.t + 18} class="fill-ink text-[13px] font-semibold">
          {`ECE ${ece.toFixed(3)}`}
        </text>
        <text x={M.l + 8} y={M.t + 32} class="fill-ink-muted text-[11px]">
          {`Brier ${brier.toFixed(3)}, ${n} cases`}
        </text>
      </svg>
      <p class="mt-1.5 flex flex-wrap gap-1.5 text-xs">
        <span class="st-legend st-tone-info">bin: dot area follows the cases in it</span>
        <span class="st-legend st-tone-muted">dashed: perfectly calibrated</span>
        {marks.map((v) => (
          <span key={v.label} class={`st-legend st-tone-${toneOf(v.stroke)}`}>
            {v.label}
          </span>
        ))}
      </p>
    </figure>
  );
}

const TONE: Record<string, string> = { good: 'bg-primary-soft', bad: 'bg-danger-soft text-danger font-semibold', plain: '' };

/** Confusion matrix as a real table. Wrong approvals and wrong rejections are marked; the rest is neutral. */
export function Confusion({ rows, columns, counts, caption }: { rows: readonly string[]; columns: readonly string[]; counts: Record<string, Record<string, number>>; caption?: ComponentChildren }) {
  const tone = (r: string, c: string): string => {
    if (r === 'not_genuine' && c === 'approved') return TONE.bad!;
    if (r === 'not_eligible' && c === 'approved') return TONE.bad!;
    if (r === 'eligible_and_genuine' && c === 'rejected') return TONE.bad!;
    if ((r === 'eligible_and_genuine' && c === 'approved') || (r !== 'eligible_and_genuine' && c === 'rejected')) return TONE.good!;
    return TONE.plain!;
  };
  return (
    <table class="w-full border-collapse text-sm">
      {caption ? <caption class="mb-1 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted">{caption}</caption> : null}
      <thead>
        <tr>
          <th scope="col" class="border-b border-line-strong bg-sunken px-2 py-1 text-start text-xs uppercase text-ink-muted">
            Truth \ decision
          </th>
          {columns.map((c) => (
            <th key={c} scope="col" class="border-b border-line-strong bg-sunken px-2 py-1 text-end text-xs uppercase text-ink-muted">
              {c.replace(/_/g, ' ')}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r}>
            <th scope="row" class="border-b border-line px-2 py-1 text-start font-normal">
              {r.replace(/_/g, ' ')}
            </th>
            {columns.map((c) => (
              <td key={c} class={`border-b border-line px-2 py-1 text-end font-mono tabular-nums ${tone(r, c)}`}>
                {counts[r]?.[c] ?? 0}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One horizontal bar per row, for share-of-cases style comparisons. Value labels are text. */
export function HBars({ rows, max, unit = '' }: { rows: readonly { label: string; value: number; cls?: string }[]; max?: number; unit?: string }) {
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul class="st-chart flex flex-col gap-1.5">
      {rows.map((r) => {
        const tone = toneOf(r.cls ?? 'fill-info-strong');
        return (
          <li key={r.label} class="grid grid-cols-[9rem_1fr_4rem] items-center gap-2">
            <span class="truncate text-xs text-ink-muted" title={r.label}>
              {r.label}
            </span>
            <svg viewBox="0 0 100 9" preserveAspectRatio="none" class={`h-2.5 w-full st-tone-${tone}`} aria-hidden="true">
              <rect width="100" height="9" rx="4" class="fill-sunken" />
              <rect width={Math.max(0, Math.min(100, (r.value / top) * 100))} height="9" rx="4" class={`${r.cls ?? 'fill-info-strong'} st-bar-fill st-glow`} />
            </svg>
            <span class="text-end font-mono text-xs tabular-nums">
              {r.value}
              {unit}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
