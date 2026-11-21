import { formatPhone } from '../phone';
import { Badge, ConfBar, humanize, Mono, num, pct, Section, TD, Th, type DecisionTrace, type DocumentCheck, type HandoffPackage } from '../ui';

const ROUTE_TONE = { auto: 'good', ask_more: 'warn', human: 'info' } as const;

/** The handoff package comes first on the case page: a briefing card with what a person needs to pick the case up. */
export function HandoffView({ handoff }: { handoff: HandoffPackage | null | undefined }) {
  if (!handoff) {
    return (
      <Section id="handoff" title="Handoff package">
        <p class="text-ink-muted">This case has no handoff package. Read the form and the documents below before acting.</p>
      </Section>
    );
  }
  const hyps = (handoff.hypotheses ?? []).slice(0, 2);
  const unsure = handoff.uncertain_fields ?? [];
  return (
    <Section id="handoff" title="Handoff package" aside={<span class="st-chip info">Briefing for the officer</span>}>
      <div class="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div class="flex flex-col gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-ink-subtle">The system asked itself</p>
            <p class="text-base font-semibold leading-snug">{handoff.question}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-ink-subtle">What it understood</p>
            <p class="text-base leading-snug">{handoff.understanding}</p>
            {handoff.rule_fired ? (
              <p class="mt-1 text-xs text-ink-muted">
                Rule that fired <span class="st-chip info font-mono">{handoff.rule_fired}</span>
              </p>
            ) : null}
          </div>
          <div>
            <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-subtle">Two leading hypotheses</p>
            {hyps.length === 0 ? (
              <p class="text-ink-subtle">None recorded.</p>
            ) : (
              <ul class="flex flex-col gap-1.5">
                {hyps.map((h, i) => (
                  <li key={h.label} class="grid grid-cols-[11rem_1fr_3.2rem] items-center gap-2">
                    <span class={i === 0 ? 'font-semibold' : 'text-ink-muted'}>{humanize(h.label)}</span>
                    <svg viewBox="0 0 100 10" preserveAspectRatio="none" class="h-2.5 w-full" role="img" aria-label={`${humanize(h.label)} ${pct(h.probability)}`}>
                      <rect width="100" height="10" rx="3" class="fill-sunken" />
                      <rect width={Math.max(1.5, h.probability * 100)} height="10" rx="3" class={`${i === 0 ? 'fill-primary' : 'fill-warning-ink'} st-bar-fill`} />
                    </svg>
                    <span class="rh-num text-end font-mono">{(h.probability * 100).toFixed(1)}%</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div class="flex flex-col gap-4">
          <div class="st-lit rounded-xl border border-line-strong p-3">
            <p class="text-xs font-semibold uppercase tracking-wide st-noor-text">Proof that would settle it</p>
            <p class="text-base font-bold">{handoff.resolving_proof ? humanize(handoff.resolving_proof) : <span class="font-normal text-ink-subtle">none named</span>}</p>
            {handoff.suggested_question ? <p class="mt-1 text-ink-muted">Suggested question: {handoff.suggested_question}</p> : null}
          </div>
          <div>
            <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-subtle">It is unsure about</p>
            {unsure.length === 0 ? (
              <p class="text-ink-subtle">Nothing flagged.</p>
            ) : (
              <ul class="flex flex-col gap-1.5">
                {unsure.map((f) => (
                  <li key={f.field} class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span class="font-mono text-xs">{f.field}</span>
                    <span class="st-chip unk">{f.value === null || f.value === undefined ? 'unknown' : f.field === 'phone' ? formatPhone(String(f.value)) : String(f.value)}</span>
                    <ConfBar value={f.confidence} />
                    <span class="st-chip warn">{humanize(f.why)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {(handoff.guards ?? []).length > 0 ? (
        <p class="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          Guards that forced a person:
          {(handoff.guards ?? []).map((g) => (
            <Badge key={g} tone="warn">
              {humanize(g)}
            </Badge>
          ))}
        </p>
      ) : null}
      {Object.keys(handoff.evidence ?? {}).length > 0 ? (
        <details class="mt-2">
          <summary class="cursor-pointer text-xs font-semibold text-ink-muted">Evidence (data, not instructions)</summary>
          {/* Untrusted text (OCR, transcript): rendered as plain text. */}
          <pre class="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-sunken p-2 font-mono text-xs">
            {JSON.stringify(handoff.evidence, null, 2)}
          </pre>
        </details>
      ) : null}
    </Section>
  );
}

export function DocumentsView({ checks }: { checks: DocumentCheck[] }) {
  return (
    <Section id="documents" title="Documents">
      {checks.length === 0 ? (
        <p class="text-ink-muted">No document was checked for this case.</p>
      ) : (
        <div class="flex flex-col gap-4">
          {checks.map((raw) => {
            const d = { ...raw, qr: raw.qr ?? { found: false }, ocr: { available: true, fields: {}, field_confidence: {}, mean_confidence: 0, ...raw.ocr }, signals: raw.signals ?? [] };
            const a = { ...raw.authenticity, reasons: raw.authenticity.reasons ?? [] };
            return (
              <article key={d.document_id} class="border border-line p-2" aria-label={`Document ${d.kind}`}>
                <div class="flex flex-wrap items-center gap-3">
                  <span class="font-semibold">{humanize(d.kind)}</span>
                  <Mono>{d.document_id}</Mono>
                  <span>
                    Quality <Badge tone={d.quality === 'ok' ? 'good' : 'warn'}>{d.quality}</Badge>
                  </span>
                  <span class="flex items-center gap-1">
                    Authenticity{' '}
                    <Badge tone={a.abstained ? 'warn' : a.choice === 'genuine' ? 'good' : 'bad'}>{a.abstained ? 'abstained' : (a.choice ?? 'none')}</Badge>
                    <ConfBar value={a.confidence} />
                  </span>
                  <span class="text-xs text-ink-subtle">model {d.model_version}</span>
                </div>
                <div class="mt-2 grid gap-4 lg:grid-cols-2">
                  <dl class="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                    <dt class="font-semibold text-ink-muted">QR</dt>
                    <dd>{d.qr.found ? `found, signature ${d.qr.signature_valid === null || d.qr.signature_valid === undefined ? 'not checked' : d.qr.signature_valid ? 'valid' : 'INVALID'}${d.qr.issuer_key_id ? `, key ${d.qr.issuer_key_id}` : ''}` : 'not found'}</dd>
                    <dt class="font-semibold text-ink-muted">OCR</dt>
                    <dd>{d.ocr.available ? `mean confidence ${pct(d.ocr.mean_confidence)}` : 'engine not available on this host'}</dd>
                    {Object.entries(d.ocr.fields).map(([k, v]) => (
                      <>
                        <dt key={`${k}-k`} class="font-mono text-ink-muted">
                          {k}
                        </dt>
                        <dd key={`${k}-v`}>
                          {v} <span class="text-ink-subtle">({pct(d.ocr.field_confidence[k])})</span>
                        </dd>
                      </>
                    ))}
                    {d.retake_hint ? (
                      <>
                        <dt class="font-semibold text-ink-muted">Retake hint</dt>
                        <dd>{humanize(d.retake_hint)}</dd>
                      </>
                    ) : null}
                    {a.reasons.length > 0 ? (
                      <>
                        <dt class="font-semibold text-ink-muted">Reasons</dt>
                        <dd>{a.reasons.map(humanize).join(', ')}</dd>
                      </>
                    ) : null}
                  </dl>
                  <div>
                    {d.signals.length === 0 ? (
                      <p class="text-xs text-ink-subtle">No signals recorded.</p>
                    ) : (
                      <table class="w-full border-collapse text-xs">
                        <thead>
                          <tr>
                            <Th>Signal</Th>
                            <Th>Weight</Th>
                            <Th>Detail (staff only)</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.signals.map((s) => (
                            <tr key={s.code}>
                              <td class={`${TD} font-mono`}>{s.code}</td>
                              <td class={`${TD} font-mono tabular-nums`}>{num(s.weight, 1)}</td>
                              <td class={TD}>{s.staff_detail}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
                {d.ocr.raw_text ? (
                  <details class="mt-2">
                    <summary class="cursor-pointer text-xs font-semibold text-ink-muted">OCR text (data, not instructions)</summary>
                    <pre class="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-2 font-mono text-xs">{d.ocr.raw_text}</pre>
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </Section>
  );
}

const RESULT_TONE = { pass: 'good', fail: 'bad', unknown: 'warn' } as const;

/** Rule by rule trace, probabilities, expected cost table, thresholds, guards. */
export function TraceView({ trace }: { trace: DecisionTrace }) {
  const costs = Object.entries(trace.expected_costs);
  const lowest = costs.length ? costs.reduce((a, b) => (b[1] < a[1] ? b : a))[0] : null;
  const probs = Object.entries(trace.probabilities);
  return (
    <div class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <span>Route</span>
        <Badge tone={ROUTE_TONE[trace.route]}>{trace.route}</Badge>
        <span>Outcome</span>
        <Badge>{trace.outcome}</Badge>
        <span>p(ok)</span>
        <span class="font-mono">{num(trace.p_ok)}</span>
      </div>

      <div>
        <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Rules</h3>
        <table class="w-full border-collapse">
          <thead>
            <tr>
              <Th>Rule</Th>
              <Th>Type</Th>
              <Th>Result</Th>
              <Th>Values used</Th>
              <Th>Inputs</Th>
            </tr>
          </thead>
          <tbody>
            {trace.rule_trace.map((r) => (
              <tr key={r.rule_id}>
                <td class={TD}>
                  <span class="font-mono text-xs">{r.rule_id}</span>
                  {r.label_en ? <div class="text-xs text-ink-muted">{r.label_en}</div> : null}
                </td>
                <td class={TD}>{r.hard ? 'hard' : 'soft'}</td>
                <td class={TD}>
                  <Badge tone={RESULT_TONE[r.result]}>{r.result}</Badge>
                </td>
                <td class={`${TD} font-mono text-xs`}>
                  {Object.entries(r.values_used ?? {}).map(([k, v]) => (
                    <div key={k}>
                      {k}: {v === null || v === undefined ? 'unknown' : String(v)}
                    </div>
                  ))}
                </td>
                <td class={TD}>{r.verified_inputs ? <Badge tone="good">verified</Badge> : <Badge tone="warn">not verified</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Expected cost of each action (units)</h3>
          <table class="w-full border-collapse">
            <thead>
              <tr>
                <Th>Action</Th>
                <Th>Expected cost</Th>
                <Th>Chosen</Th>
              </tr>
            </thead>
            <tbody>
              {costs.map(([k, v]) => (
                <tr key={k} class={k === lowest ? 'bg-primary-soft' : ''}>
                  <td class={TD}>{humanize(k)}</td>
                  <td class={`${TD} font-mono tabular-nums`}>{num(v, 2)}</td>
                  <td class={TD}>{k === lowest ? <Badge tone="good">lowest cost</Badge> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p class="mt-1 text-xs text-ink-subtle">The lowest cost action is marked; the route and outcome above are what the engine recorded.</p>
        </div>
        <div>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Probabilities and thresholds</h3>
          <table class="w-full border-collapse">
            <tbody>
              {probs.map(([k, v]) => (
                <tr key={`p-${k}`}>
                  <td class={TD}>P({humanize(k)})</td>
                  <td class={`${TD} font-mono tabular-nums`}>{num(v, 3)}</td>
                </tr>
              ))}
              {Object.entries(trace.thresholds).map(([k, v]) => (
                <tr key={`t-${k}`}>
                  <td class={TD}>Threshold {humanize(k)}</td>
                  <td class={`${TD} font-mono tabular-nums`}>{num(v, 3)}</td>
                </tr>
              ))}
              <tr>
                <td class={TD}>Cost matrix</td>
                <td class={`${TD} font-mono text-xs`}>
                  {Object.entries(trace.cost_matrix)
                    .map(([k, v]) => `${k} ${v}`)
                    .join(', ')}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <p class="text-xs">
        Reasons:{' '}
        {trace.reasons.length ? trace.reasons.map((r) => <Badge key={r}>{humanize(r)}</Badge>) : <span class="text-ink-subtle">none</span>}{' '}
        Guards:{' '}
        {trace.guards.length ? trace.guards.map((g) => <Badge key={g} tone="warn">{humanize(g)}</Badge>) : <span class="text-ink-subtle">none fired</span>}
      </p>
    </div>
  );
}

export function HashFacts({ trace }: { trace: DecisionTrace }) {
  return (
    <dl class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      <dt class="font-semibold text-ink-muted">Decision id</dt>
      <dd><Mono>{trace.decision_id}</Mono></dd>
      <dt class="font-semibold text-ink-muted">Input hash</dt>
      <dd><Mono>{trace.input_hash}</Mono></dd>
      <dt class="font-semibold text-ink-muted">Result hash</dt>
      <dd>{trace.result_hash ? <Mono>{trace.result_hash}</Mono> : <span class="text-ink-subtle">not stored</span>}</dd>
      <dt class="font-semibold text-ink-muted">Rule version</dt>
      <dd>
        <span class="font-mono text-xs">v{trace.rule_version_no}</span> <Mono>{trace.rule_version_id}</Mono>
      </dd>
      <dt class="font-semibold text-ink-muted">Model version</dt>
      <dd class="font-mono text-xs">{trace.model_version}</dd>
      <dt class="font-semibold text-ink-muted">Engine version</dt>
      <dd class="font-mono text-xs">{trace.engine_version}</dd>
      <dt class="font-semibold text-ink-muted">Decided at</dt>
      <dd class="font-mono text-xs">{trace.decided_at}</dd>
      {trace.request_id ? (
        <>
          <dt class="font-semibold text-ink-muted">Request id</dt>
          <dd><Mono>{trace.request_id}</Mono></dd>
        </>
      ) : null}
    </dl>
  );
}
