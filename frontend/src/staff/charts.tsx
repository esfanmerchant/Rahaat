import type { ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';

/**
 * Hand-written SVG charts for the evaluation pages. No chart library (CLAUDE.md).
 * Colours are classes (the strict CSP has no inline style), and every chart has a text alternative.
 */

const W = 460;
const H = 280;
const M = { l: 46, r: 14, t: 12, b: 38 };

export type Pt = readonly [number, number];
export interface Series {
  name: string;
  points: readonly Pt[];
  /** Tailwind stroke class, from the tokens only. */
  stroke: string;
  dashed?: boolean;
  step?: boolean;
}
export interface VLine {
  x: number;
  label: string;
  stroke: string;
  /** Row for the label so two labels do not overlap. */
  row?: number;
}
export interface Dot {
  x: number;
  y: number;
  label: string;
  fill: string;
}

function ticks(lo: number, hi: number, n = 5): number[] {
  const out: number[] = [];
  for (let i = 0; i <= n; i++) out.push(lo + ((hi - lo) * i) / n);
  return out;
}

const fmtTick = (v: number): string => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));

export interface XYProps {
  id: string;
  title: string;
  xLabel: string;
  yLabel: string;
  series: readonly Series[];
  xDomain: Pt;
  yDomain: Pt;
  vlines?: readonly VLine[];
  dots?: readonly Dot[];
  diagonal?: boolean;
  /** One sentence for screen readers and for people who do not see the picture. */
  summary: string;
}

export function XYChart({ id, title, xLabel, yLabel, series, xDomain, yDomain, vlines = [], dots = [], diagonal, summary }: XYProps) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const [x0, x1] = xDomain;
  const [y0, y1] = yDomain;
  const sx = (v: number) => M.l + ((v - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - ((v - y0) / (y1 - y0 || 1)) * (H - M.t - M.b);
  const clampX = (v: number) => Math.max(M.l, Math.min(W - M.r, v));
  const path = (s: Series) => {
    const pts = [...s.points].sort((a, b) => a[0] - b[0]);
    if (pts.length === 0) return '';
    let d = `M${sx(pts[0]![0]).toFixed(1)} ${sy(pts[0]![1]).toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const p = pts[i]!;
      if (s.step) d += `H${sx(p[0]).toFixed(1)}V${sy(p[1]).toFixed(1)}`;
      else d += `L${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`;
    }
    return d;
  };
  return (
    <figure class="st-chart relative m-0">
      <figcaption id={`${id}-t`} class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        {title}
      </figcaption>
      {tip ? (
        <div class="st-tip" style={{ left: `${(tip.x / W) * 100}%`, top: `${(tip.y / H) * 100 + 8}%`, transform: 'translateX(-50%)' }} role="tooltip">
          {tip.text}
        </div>
      ) : null}
      <svg viewBox={`0 0 ${W} ${H}`} class="block w-full max-w-[520px]" role="img" aria-labelledby={`${id}-t ${id}-d`}>
        <desc id={`${id}-d`}>{summary}</desc>
        {ticks(y0, y1).map((t) => (
          <g key={`y${t}`}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} class="stroke-line" stroke-width="1" />
            <text x={M.l - 5} y={sy(t) + 3} text-anchor="end" class="fill-ink-muted text-[10px]">
              {fmtTick(t)}
            </text>
          </g>
        ))}
        {ticks(x0, x1).map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={H - M.b} y2={H - M.b + 4} class="stroke-line-strong" stroke-width="1" />
            <text x={sx(t)} y={H - M.b + 15} text-anchor="middle" class="fill-ink-muted text-[10px]">
              {fmtTick(t)}
            </text>
          </g>
        ))}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="none" class="stroke-line-strong" stroke-width="1" />
        {diagonal ? <line x1={sx(x0)} y1={sy(y0)} x2={sx(x1)} y2={sy(y1)} class="stroke-ink-subtle" stroke-width="1" stroke-dasharray="4 3" /> : null}
        {vlines.map((v) => (
          <g key={v.label}>
            <line x1={clampX(sx(v.x))} x2={clampX(sx(v.x))} y1={M.t} y2={H - M.b} class={v.stroke} stroke-width="1.5" stroke-dasharray="5 3" />
            <text x={clampX(sx(v.x)) + (sx(v.x) > W - 150 ? -4 : 4)} y={M.t + 11 + (v.row ?? 0) * 12} text-anchor={sx(v.x) > W - 150 ? 'end' : 'start'} class="fill-ink text-[10px]">
              {v.label}
            </text>
          </g>
        ))}
        {series.map((s) => (
          <path
            key={s.name}
            d={path(s)}
            fill="none"
            class={`${s.stroke} ${s.dashed ? 'st-fade' : 'st-line'}`}
            pathLength={s.dashed ? undefined : 100}
            stroke-width="2.25"
            stroke-linejoin="round"
            stroke-linecap="round"
            stroke-dasharray={s.dashed ? '6 3' : undefined}
          />
        ))}
        {series.map((s) => {
          const pts = [...s.points].sort((a, b) => a[0] - b[0]);
          const stride = Math.max(1, Math.ceil(pts.length / 24));
          return pts
            .filter((_, i) => i % stride === 0)
            .map((p) => {
              const text = `${s.name}: ${xLabel} ${fmtTick(p[0])}, ${yLabel} ${fmtTick(p[1])}`;
              const show = () => setTip({ x: sx(p[0]), y: sy(p[1]), text });
              return (
                <circle
                  key={`${s.name}-${p[0]}-${p[1]}`}
                  cx={sx(p[0])}
                  cy={sy(p[1])}
                  r="5"
                  fill="transparent"
                  class="cursor-crosshair outline-none [&:focus-visible]:stroke-focus"
                  stroke-width="2"
                  tabIndex={0}
                  role="img"
                  aria-label={text}
                  onMouseEnter={show}
                  onFocus={show}
                  onMouseLeave={() => setTip(null)}
                  onBlur={() => setTip(null)}
                />
              );
            });
        })}
        {dots.map((d) => (
          <g key={d.label}>
            <circle cx={sx(d.x)} cy={sy(d.y)} r="5" class={`${d.fill} st-pt`} stroke-width="1.5">
              <title>{d.label}</title>
            </circle>
          </g>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 4} text-anchor="middle" class="fill-ink text-[11px]">
          {xLabel}
        </text>
        <text transform={`translate(11 ${(M.t + H - M.b) / 2}) rotate(-90)`} text-anchor="middle" class="fill-ink text-[11px]">
          {yLabel}
        </text>
      </svg>
      {series.length > 1 || dots.length > 0 ? (
        <p class="mt-1 flex flex-wrap gap-x-3 text-xs text-ink-muted">
          {series.map((s) => (
            <span key={s.name}>
              <svg width="18" height="8" class="inline" aria-hidden="true">
                <line x1="0" x2="18" y1="4" y2="4" class={s.stroke} stroke-width="2" stroke-dasharray={s.dashed ? '5 3' : undefined} />
              </svg>{' '}
              {s.name}
            </span>
          ))}
          {dots.map((d) => (
            <span key={d.label}>
              <svg width="10" height="10" class="inline" aria-hidden="true">
                <circle cx="5" cy="5" r="4" class={d.fill} stroke-width="1.5" />
              </svg>{' '}
              {d.label}
            </span>
          ))}
        </p>
      ) : null}
    </figure>
  );
}

export interface BinIn {
  count: number;
  mean_predicted?: number | null;
  observed_rate?: number | null;
}

/** Reliability diagram: the dots should sit on the diagonal. The dot area follows how many cases fell in the bin. */
export function ReliabilityChart({ id, bins, ece, brier, n }: { id: string; bins: readonly BinIn[]; ece: number; brier: number; n: number }) {
  const used = bins.filter((b) => b.count > 0 && b.mean_predicted != null && b.observed_rate != null);
  const maxCount = Math.max(1, ...used.map((b) => b.count));
  const sx = (v: number) => M.l + v * (W - M.l - M.r);
  const sy = (v: number) => H - M.b - v * (H - M.t - M.b);
  return (
    <figure class="st-chart m-0">
      <figcaption id={`${id}-t`} class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
        Reliability: said versus happened
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} class="block w-full max-w-[520px]" role="img" aria-labelledby={`${id}-t ${id}-d`}>
        <desc id={`${id}-d`}>{`Calibration on ${n} cases. Expected calibration error ${ece.toFixed(3)}, Brier score ${brier.toFixed(3)}. ${used.length} bins have cases.`}</desc>
        {ticks(0, 1).map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} class="stroke-line" stroke-width="1" />
            <text x={M.l - 5} y={sy(t) + 3} text-anchor="end" class="fill-ink-muted text-[10px]">
              {t.toFixed(1)}
            </text>
            <text x={sx(t)} y={H - M.b + 15} text-anchor="middle" class="fill-ink-muted text-[10px]">
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        <rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} fill="none" class="stroke-line-strong" stroke-width="1" />
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} class="stroke-ink-subtle" stroke-width="1" stroke-dasharray="4 3" />
        {used.map((b) => (
          <circle key={`${b.mean_predicted}`} cx={sx(b.mean_predicted as number)} cy={sy(b.observed_rate as number)} r={3 + 6 * Math.sqrt(b.count / maxCount)} class="fill-info-soft stroke-info-strong st-pt" stroke-width="1.5" tabIndex={0} role="img" aria-label={`${b.count} cases: said ${(b.mean_predicted as number).toFixed(2)}, happened ${(b.observed_rate as number).toFixed(2)}`}>
            <title>{`${b.count} cases: said ${(b.mean_predicted as number).toFixed(2)}, happened ${(b.observed_rate as number).toFixed(2)}`}</title>
          </circle>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 4} text-anchor="middle" class="fill-ink text-[11px]">
          What the model said (mean p_ok in the bin)
        </text>
        <text transform={`translate(11 ${(M.t + H - M.b) / 2}) rotate(-90)`} text-anchor="middle" class="fill-ink text-[11px]">
          What happened (share truly OK)
        </text>
        <text x={M.l + 8} y={M.t + 16} class="fill-ink text-[12px] font-semibold">
          {`ECE ${ece.toFixed(3)}`}
        </text>
        <text x={M.l + 8} y={M.t + 30} class="fill-ink-muted text-[10px]">
          {`Brier ${brier.toFixed(3)}, ${n} cases`}
        </text>
      </svg>
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
    <ul class="st-chart flex flex-col gap-1">
      {rows.map((r) => (
        <li key={r.label} class="grid grid-cols-[9rem_1fr_4rem] items-center gap-2">
          <span class="truncate text-xs text-ink-muted" title={r.label}>
            {r.label}
          </span>
          <svg viewBox="0 0 100 8" preserveAspectRatio="none" class="h-2 w-full" aria-hidden="true">
            <rect width="100" height="8" rx="3" class="fill-sunken" />
            <rect width={Math.max(0, Math.min(100, (r.value / top) * 100))} height="8" rx="3" class={`${r.cls ?? 'fill-info-strong'} st-bar-fill`} />
          </svg>
          <span class="text-end font-mono text-xs tabular-nums">
            {r.value}
            {unit}
          </span>
        </li>
      ))}
    </ul>
  );
}
