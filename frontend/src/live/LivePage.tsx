import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Emblem } from '../shared/components/Emblem';
import { PROTOTYPE_LABEL_EN, PROTOTYPE_LABEL_UR } from '../shared/components/PrototypeFooter';
import { Counter } from './Counter';
import { Sankey } from './Sankey';
import type { HoverInfo, LabelPoint, SceneHandle } from './scene';
import { detectCapability, LANE_COLOR, LANE_LABEL, NOOR, SHIELD_COLOR, type Capability, type Pulse } from './types';
import { usePulse } from './usePulse';

const LABELS: Record<string, string> = {
  horizon: 'Synthetic cases',
  gate: 'Cost-matrix gate',
  homes: 'Homes reached',
  desk: 'A person will check',
  shield: 'Scam shield',
};

const WHY: Record<NonNullable<Capability['reason']>, string> = {
  'webgl-unavailable': 'WebGL is not available on this device, so this is the static view of the same numbers.',
  'reduced-motion': 'Reduced motion is on, so this is the static view of the same numbers.',
  'save-data': 'Data saver is on, so the 3D scene was not downloaded. This is the static view of the same numbers.',
};

function signature(p: Pulse): string {
  const r = p.replay;
  return `${r.cases_scored}|${r.rule_version_no}|${r.model_version}|${r.cases.length}|${JSON.stringify(r.headline)}`;
}

function summary(p: Pulse): string {
  const h = p.replay.headline;
  const l = p.live;
  const parts = [
    `Live: ${l.payments.sent} payments sent (PKR ${l.payments.sent_amount_pkr.toLocaleString('en-US')}), ${l.payments.settled} settled, ${l.scam.reports} scam reports, ${l.scam.blocked} blocked, audit chain of ${l.audit_chain_length} entries.`,
  ];
  if (h) {
    parts.push(
      `Replay of ${h.cases} synthetic labelled cases: ${h.approved} approved, ${h.asked_for_proof} asked for proof, ${h.sent_to_person} sent to a person, ${h.rejected} rejected. Wrong approvals ${h.wrong_approvals}. Silent guesses ${h.silent_guesses}.`,
    );
  }
  return parts.join(' ');
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div class="flex items-baseline justify-between gap-3">
      <dt class="text-night-muted">{label}</dt>
      <dd class={`m-0 text-base font-bold ${tone ?? 'text-night-ink'}`}>
        <Counter value={value} />
      </dd>
    </div>
  );
}

function Legend() {
  const items: { c: string; t: string }[] = [
    { c: LANE_COLOR.approve, t: LANE_LABEL.approve },
    { c: LANE_COLOR.ask, t: LANE_LABEL.ask },
    { c: LANE_COLOR.human, t: LANE_LABEL.human },
    { c: LANE_COLOR.reject, t: LANE_LABEL.reject },
    { c: SHIELD_COLOR, t: 'Scam reports (sparks on the shield)' },
  ];
  return (
    <ul class="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-night-muted" aria-label="Legend">
      {items.map((i, k) => (
        <li key={i.t} class="flex items-center gap-1.5">
          {k === 4 ? (
            <svg width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">
              <polygon points="0,-5.5 4.8,-2.7 4.8,2.7 0,5.5 -4.8,2.7 -4.8,-2.7" fill="none" stroke={i.c} stroke-width="1.6" />
            </svg>
          ) : (
            <span class="inline-block size-2.5 rounded-full" style={{ background: i.c, boxShadow: `0 0 8px ${i.c}` }} />
          )}
          {i.t}
        </li>
      ))}
    </ul>
  );
}

function HoverCard({ info, box }: { info: HoverInfo; box: { w: number; h: number } }) {
  const left = Math.min(Math.max(8, info.x + 16), box.w - 270);
  const top = Math.min(Math.max(8, info.y - 8), box.h - 150);
  return (
    <div
      role="status"
      class="pointer-events-none absolute z-20 w-64 rounded-xl border border-night-line bg-night-2 p-3 text-sm shadow-float"
      style={{ left: `${left}px`, top: `${top}px` }}
    >
      <p class="m-0 flex items-center gap-2 font-bold">
        <span class="inline-block size-2.5 rounded-full" style={{ background: LANE_COLOR[info.lane] }} />
        {LANE_LABEL[info.lane]}
      </p>
      <dl class="m-0 mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-night-muted">
        <dt>p_ok</dt>
        <dd class="m-0 font-mono text-night-ink">{info.c.p_ok.toFixed(2)}</dd>
        <dt>reason</dt>
        <dd class="m-0 break-words font-mono text-night-ink">{info.c.reason_code}</dd>
        <dt>kind</dt>
        <dd class="m-0 font-mono text-night-ink">{info.c.kind}</dd>
      </dl>
      <p class="m-0 mt-2 text-xs font-bold" style={{ color: NOOR }}>
        Synthetic case
      </p>
    </div>
  );
}

function SceneLayer({ pulse, onFail, setHover }: { pulse: Pulse | null; onFail: () => void; setHover: (h: HoverInfo | null) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const handle = useRef<SceneHandle | null>(null);
  const labelEls = useRef<Record<string, HTMLElement | null>>({});
  const [ready, setReady] = useState(false);
  const failRef = useRef(onFail);
  failRef.current = onFail;
  const hoverRef = useRef(setHover);
  hoverRef.current = setHover;

  useEffect(() => {
    let dead = false;
    let created: SceneHandle | null = null;
    // three.js is fetched here and only here: not for the static view, not for the citizen app.
    void import('./scene')
      .then((m) => {
        if (dead || !canvas.current || !host.current) return;
        created = m.createScene(canvas.current, host.current, {
          onHover: (h) => hoverRef.current(h),
          onFail: () => failRef.current(),
          onLabels: (list: LabelPoint[]) => {
            for (const l of list) {
              const el = labelEls.current[l.id];
              if (!el) continue;
              el.style.transform = `translate(${Math.round(l.x)}px, ${Math.round(l.y)}px) translate(-50%, -50%)`;
              el.style.opacity = l.visible ? '1' : '0';
            }
          },
        });
        handle.current = created;
        setReady(true);
      })
      .catch(() => failRef.current());
    return () => {
      dead = true;
      created?.dispose();
      handle.current = null;
    };
  }, []);

  const sig = pulse ? signature(pulse) : '';
  useEffect(() => {
    if (!ready || !pulse) return;
    handle.current?.setCases(pulse.replay.cases);
  }, [ready, sig]);
  const blocked = pulse?.live.scam.blocked ?? 0;
  useEffect(() => {
    if (ready) handle.current?.setScamCount(blocked);
  }, [ready, blocked]);

  const label = pulse ? `The Loom of Light. ${summary(pulse)}` : 'The Loom of Light. Loading the live decision engine.';
  return (
    <div ref={host} class="absolute inset-0">
      <canvas
        ref={canvas}
        tabIndex={0}
        role="img"
        aria-label={`${label} Drag to orbit, scroll or pinch to zoom, arrow keys and plus and minus also work.`}
        class="block size-full touch-none cursor-grab outline-none focus-visible:ring-2 focus-visible:ring-noor active:cursor-grabbing"
      />
      <div aria-hidden="true" class="pointer-events-none absolute inset-0 hidden overflow-hidden md:block">
        {Object.entries(LABELS).map(([id, text]) => (
          <span
            key={id}
            ref={(el) => {
              labelEls.current[id] = el;
            }}
            class="absolute left-0 top-0 whitespace-nowrap text-xs font-bold uppercase tracking-wider text-night-ink opacity-0 transition-opacity [text-shadow:0_0_8px_#070b1d,0_0_3px_#070b1d]"
          >
            {text}
          </span>
        ))}
      </div>
    </div>
  );
}

function failureText(kind: string): { title: string; body: string } {
  if (kind === 'offline') return { title: 'You are offline', body: 'The live numbers need a connection. This page tries again by itself.' };
  if (kind === 'network') return { title: 'Cannot reach the server', body: 'The request did not get through. This page tries again by itself every 15 seconds.' };
  if (kind === 'rate_limited') return { title: 'Too many requests', body: 'The public pulse is rate limited per network. Wait a minute and try again.' };
  if (kind === 'forbidden' || kind === 'unauthenticated') return { title: 'Not allowed', body: 'The server refused this request.' };
  return { title: 'The live engine did not answer', body: 'The server returned an error. Nothing is shown rather than a made-up number.' };
}

export default function LivePage() {
  const { state, reload } = usePulse();
  const cap = useMemo(detectCapability, []);
  const [sceneFailed, setSceneFailed] = useState(false);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [full, setFull] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth < 768);
  const [panels, setPanels] = useState(() => window.innerWidth >= 768);
  const root = useRef<HTMLElement>(null);
  const [box, setBox] = useState({ w: window.innerWidth, h: window.innerHeight });

  useEffect(() => {
    const prev = document.title;
    document.title = 'Rahat Live (Prototype)';
    return () => {
      document.title = prev;
    };
  }, []);
  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement !== null);
    const onResize = () => {
      setBox({ w: root.current?.clientWidth ?? window.innerWidth, h: root.current?.clientHeight ?? window.innerHeight });
      setNarrow(window.innerWidth < 768);
    };
    document.addEventListener('fullscreenchange', onFs);
    window.addEventListener('resize', onResize);
    onResize();
    return () => {
      document.removeEventListener('fullscreenchange', onFs);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  const pulse = state.kind === 'ready' ? state.pulse : null;
  const head = pulse?.replay.headline ?? null;
  const scene = cap.ok && !sceneFailed;
  const why = !cap.ok && cap.reason ? WHY[cap.reason] : sceneFailed ? WHY['webgl-unavailable'] : null;
  const toggleFull = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void (root.current ?? document.documentElement).requestFullscreen?.().catch(() => undefined);
  };
  const showEval = head !== null && (panels || narrow);
  const big = full ? 'text-6xl' : 'text-3xl md:text-5xl';

  return (
    <main ref={root} dir="ltr" lang="en" class="fixed inset-0 overflow-hidden bg-night text-night-ink" aria-label="Rahat Live">
      {scene ? (
        <SceneLayer pulse={pulse} onFail={() => setSceneFailed(true)} setHover={setHover} />
      ) : (
        <div class="rh-lattice-night absolute inset-0 overflow-y-auto">
          <div class="mx-auto flex min-h-full max-w-[1280px] flex-col justify-center pb-72 pt-32 md:pb-40">
            {head && pulse ? <Sankey headline={head} source={pulse.replay.replay_source} /> : null}
          </div>
        </div>
      )}
      {scene && hover ? <HoverCard info={hover} box={box} /> : null}

      <p class="sr-only" aria-live="polite">
        {pulse ? summary(pulse) : 'Loading.'}
      </p>

      <header class="pointer-events-none absolute inset-x-0 top-0 z-10 flex flex-wrap items-start justify-between gap-x-2 gap-y-1 p-3 md:grid md:grid-cols-[1fr_auto] md:p-5">
        <div class="pointer-events-auto flex items-center gap-3">
          <Emblem size={full ? 60 : narrow ? 34 : 44} tone="night" animate />
          <h1 class={`m-0 flex items-baseline gap-3 font-black tracking-tight ${full ? 'text-4xl' : 'text-xl md:text-3xl'}`}>
            Rahat Live
            <span lang="ur" dir="rtl" class="font-bold leading-[1.8] text-noor">
              راحت
            </span>
          </h1>
        </div>
        <div class="pointer-events-auto flex gap-2">
          <button
            type="button"
            onClick={() => setPanels(!panels)}
            aria-pressed={panels}
            class="min-h-10 whitespace-nowrap rounded-lg border border-night-line bg-night-2 px-3 text-xs font-bold text-night-ink hover:border-noor focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor md:text-sm"
          >
            {panels ? 'Hide numbers' : 'Show numbers'}
          </button>
          <button
            type="button"
            onClick={toggleFull}
            aria-pressed={full}
            class="min-h-10 whitespace-nowrap rounded-lg border border-noor bg-night-3 px-3 text-xs font-bold text-noor hover:bg-night-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor md:text-sm"
          >
            {full ? 'Exit projector' : 'Projector'}
          </button>
        </div>
        <p class="m-0 basis-full text-[11px] leading-snug text-night-muted md:col-start-1 md:max-w-xl md:basis-auto md:pl-[56px] md:text-sm">
          {pulse?.replay.available
            ? `Replay: the ${pulse.replay.replay_source} (${pulse.replay.cases_scored.toLocaleString('en-US')} synthetic cases, rule version ${pulse.replay.rule_version_no}) scored by the live engine. No real people.`
            : 'Replay of the synthetic labelled eval set, scored by the live engine. No real people.'}
        </p>
      </header>

      {state.kind === 'loading' ? (
        <p role="status" class="absolute left-1/2 top-1/2 z-10 m-0 -translate-x-1/2 -translate-y-1/2 text-night-muted">
          Loading the live engine...
        </p>
      ) : null}
      {state.kind === 'error' ? (
        <div role="alert" class="absolute left-1/2 top-1/2 z-10 w-[min(26rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-night-line bg-night-2 p-5 text-center">
          <h2 class="m-0 text-lg font-bold">{failureText(state.failure.kind).title}</h2>
          <p class="mb-4 mt-2 text-sm text-night-muted">{failureText(state.failure.kind).body}</p>
          {state.failure.problem?.request_id ? <p class="mb-3 mt-0 font-mono text-xs text-night-muted">request {state.failure.problem.request_id}</p> : null}
          <button type="button" onClick={reload} class="min-h-10 rounded-lg bg-noor px-4 text-sm font-bold text-night">
            Try again
          </button>
        </div>
      ) : null}
      {pulse && !pulse.replay.available ? (
        <p role="status" class="absolute left-1/2 top-1/3 z-10 m-0 max-w-sm -translate-x-1/2 text-center text-sm text-night-muted">
          No department has published rules yet, so there is nothing to replay. The live counters still work.
        </p>
      ) : null}
      {state.kind === 'ready' && state.stale ? (
        <p role="status" class="absolute right-5 top-16 z-10 m-0 rounded-md bg-night-2 px-2 py-1 text-xs text-saffron">
          Showing the last numbers; the latest refresh failed.
        </p>
      ) : null}

      {pulse ? (
        <div class="absolute inset-x-0 bottom-0 z-10 flex max-h-[58dvh] flex-col gap-2 overflow-y-auto p-3 pb-[4.75rem] md:max-h-none md:overflow-visible md:p-5 md:pb-10">
          {showEval && head ? (
            <section
              aria-label="Evaluation headline"
              class="w-full rounded-xl border border-night-line bg-night/80 p-3 md:fixed md:right-5 md:top-[76px] md:w-[34rem] 2xl:w-[44rem]"
            >
              <h2 class="m-0 mb-2 text-xs font-bold uppercase tracking-wider text-noor">Measured on the synthetic labelled cases</h2>
              <dl class="m-0 grid grid-cols-3 gap-3">
                <div>
                  <dt class="text-xs text-night-muted">Wrong approvals</dt>
                  <dd class={`m-0 font-black ${big} text-noor`}>
                    <Counter value={head.wrong_approvals} />
                  </dd>
                  <dd class="m-0 text-xs text-night-muted">of {head.cases.toLocaleString('en-US')} cases</dd>
                </div>
                <div>
                  <dt class="text-xs text-night-muted">Sent to a person</dt>
                  <dd class={`m-0 font-black ${big} text-indigo-glow`}>
                    <Counter value={head.sent_to_person} />
                  </dd>
                  <dd class="m-0 text-xs text-night-muted">{head.asked_for_proof.toLocaleString('en-US')} more asked for proof</dd>
                </div>
                <div>
                  <dt class="text-xs text-night-muted">Silent guesses</dt>
                  <dd class={`m-0 font-black ${big} text-emerald-glow`}>
                    <Counter value={head.silent_guesses} />
                  </dd>
                  <dd class="m-0 text-xs text-night-muted">unknown stays unknown</dd>
                </div>
              </dl>
              <p class="m-0 mt-2 font-mono text-[11px] text-night-muted md:text-xs">
                reject at {head.thresholds.reject.toFixed(2)} | approve at {head.thresholds.approve.toFixed(2)} | confidence floor{' '}
                {head.thresholds.confidence_floor.toFixed(2)} (from the department&apos;s cost matrix)
              </p>
            </section>
          ) : null}

          {panels ? (
            <>
              <section aria-label="Live counters" class="w-full rounded-xl border border-night-line bg-night/80 p-3 text-sm md:w-72">
                <h2 class="m-0 mb-2 text-xs font-bold uppercase tracking-wider text-noor">Live in the demo departments</h2>
                <dl class="m-0 grid gap-1">
                  <Stat label="Applications" value={Object.values(pulse.live.applications_by_status).reduce((a, b) => a + b, 0)} />
                  <Stat label="Decisions: automatic" value={pulse.live.decisions_by_route.auto ?? 0} tone="text-emerald-glow" />
                  <Stat label="Decisions: proof asked" value={pulse.live.decisions_by_route.ask_more ?? 0} tone="text-saffron" />
                  <Stat label="Decisions: a person" value={pulse.live.decisions_by_route.human ?? 0} tone="text-indigo-glow" />
                  <Stat label="Decisions: hard-rule reject" value={pulse.live.decisions_by_route.reject ?? 0} tone="text-madder-glow" />
                  <Stat label="Payments sent" value={pulse.live.payments.sent} tone="text-emerald-glow" />
                  <Stat label="Payments settled" value={pulse.live.payments.settled} tone="text-emerald-glow" />
                  <Stat label="Settled (PKR, mock)" value={pulse.live.payments.settled_amount_pkr} tone="text-noor" />
                  <Stat label="Scam reports" value={pulse.live.scam.reports} tone="text-madder-glow" />
                  <Stat label="Messages blocked" value={pulse.live.scam.blocked} tone="text-madder-glow" />
                  <Stat label="Audit chain entries" value={pulse.live.audit_chain_length} />
                </dl>
              </section>
              <Legend />
            </>
          ) : null}
          {why ? <p class="m-0 text-xs text-night-muted">{why}</p> : null}
        </div>
      ) : null}

      <footer class="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex flex-wrap justify-center gap-x-6 px-3 pb-1 text-[10px] leading-tight text-night-muted md:text-[11px]">
        <span lang="en" dir="ltr">
          {PROTOTYPE_LABEL_EN}
        </span>
        <span lang="ur" dir="rtl">
          {PROTOTYPE_LABEL_UR}
        </span>
      </footer>
    </main>
  );
}
