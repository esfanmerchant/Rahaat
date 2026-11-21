import type { Headline } from './types';
import { LANE_COLOR, LANE_LABEL, NOOR, type Lane } from './types';

/**
 * The static view of the same numbers: no WebGL, no three.js, no motion. Cases flow into the gate (the eight-point star,
 * the cost-matrix decision) and out to the four outcomes, each band as wide as its share of the scored cases.
 */
export function Sankey({ headline, source }: { headline: Headline; source: string }) {
  const total = Math.max(1, headline.cases);
  const outs: { lane: Lane; n: number }[] = [
    { lane: 'approve', n: headline.approved },
    { lane: 'ask', n: headline.asked_for_proof },
    { lane: 'human', n: headline.sent_to_person },
    { lane: 'reject', n: headline.rejected },
  ];
  const H = 340;
  const top = 90;
  const gap = 30;
  const widths = outs.map((o) => (o.n === 0 ? 0 : Math.max(5, (o.n / total) * H)));
  const rightH = widths.reduce((a, b) => a + b, 0) + gap * (outs.filter((o) => o.n > 0).length - 1);
  let yl = top + 20;
  let yr = top + 20 + (H - rightH) / 2;
  const bands = outs.map((o, i) => {
    const w = widths[i] ?? 0;
    const left = (o.n / total) * H;
    const band = { ...o, w, ly: yl + left / 2, lh: left, cy: yr + w / 2 };
    yl += left;
    if (w > 0) yr += w + gap;
    return band;
  });
  const gx = 470;
  const gy = top + H / 2 + 20;
  const lx = 90;
  const rx = 860;
  const mid = (a: number, b: number) => a + (b - a) / 2;
  const star = (r: number, rot: number) =>
    Array.from({ length: 4 }, (_, k) => {
      const a = rot + (k * Math.PI) / 2;
      return `${(gx + Math.cos(a) * r).toFixed(1)},${(gy + Math.sin(a) * r).toFixed(1)}`;
    }).join(' ');
  const pct = (n: number) => `${((n / total) * 100).toFixed(1)}%`;
  return (
    <figure class="m-0 mx-auto w-full max-w-[1200px] px-3">
      <svg viewBox="0 0 1200 560" role="img" aria-labelledby="sankey-t sankey-d" class="h-auto w-full">
        <title id="sankey-t">Where the scored cases went</title>
        <desc id="sankey-d">
          {`${headline.cases} cases from ${source}: ${headline.approved} approved automatically, ${headline.asked_for_proof} asked for proof, ${headline.sent_to_person} sent to a person, ${headline.rejected} rejected by a hard rule. Wrong approvals ${headline.wrong_approvals}. Silent guesses ${headline.silent_guesses}.`}
        </desc>
        <text x={lx - 10} y={top - 6} fill="#eef0ff" font-size="17" font-weight="700">
          {`${headline.cases.toLocaleString('en-US')} synthetic cases`}
        </text>
        {bands.map((b) =>
          b.w === 0 ? null : (
            <g key={b.lane}>
              <rect x={lx - 10} y={b.ly - b.lh / 2} width="14" height={b.lh} fill={LANE_COLOR[b.lane]} />
              <path
                d={`M${lx + 4},${b.ly} C${mid(lx, rx)},${b.ly} ${mid(lx, rx)},${b.cy} ${rx},${b.cy}`}
                stroke={LANE_COLOR[b.lane]}
                stroke-opacity="0.6"
                stroke-width={Math.max(b.w, 3)}
                fill="none"
              />
            </g>
          ),
        )}
        <circle cx={gx} cy={gy} r="62" fill="#070b1d" opacity="0.88" />
        <polygon points={star(46, Math.PI / 4)} fill="#0b1026" stroke={NOOR} stroke-width="3" />
        <polygon points={star(46, 0)} fill="none" stroke={NOOR} stroke-width="3" />
        <circle cx={gx} cy={gy} r="7" fill={NOOR} />
        <text x={gx} y={gy + 84} text-anchor="middle" fill="#eef0ff" font-size="15" font-weight="700">
          Cost-matrix decision
        </text>
        {bands.map((b) => (
          <g key={`l-${b.lane}`}>
            <rect x={rx} y={b.cy - Math.max(b.w, 6) / 2} width="12" height={Math.max(b.w, 6)} rx="3" fill={LANE_COLOR[b.lane]} />
            <text x={rx + 26} y={b.cy - 2} fill="#eef0ff" font-size="19" font-weight="700">
              {LANE_LABEL[b.lane]}
            </text>
            <text x={rx + 26} y={b.cy + 20} fill="#a7aed6" font-size="16">
              {`${b.n.toLocaleString('en-US')} cases, ${pct(b.n)}`}
            </text>
          </g>
        ))}
      </svg>
    </figure>
  );
}
