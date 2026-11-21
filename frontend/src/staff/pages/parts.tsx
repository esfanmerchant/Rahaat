import { Badge, ConfBar, humanize, Mono, num, pct, Section, TD, Th, type DecisionTrace, type DocumentCheck, type HandoffPackage } from '../ui';

const ROUTE_TONE = { auto: 'good', ask_more: 'warn', human: 'info' } as const;

/** The handoff package comes first on the case page: what a person needs to pick the case up. */
export function HandoffView({ handoff }: { handoff: HandoffPackage | null | undefined }) {
  if (!handoff) {
    return (
      <Section id="handoff" title="Handoff package">
        <p class="text-ink-muted">This case has no handoff package. Read the form and the documents below before acting.</p>
      </Section>
    );
  }
  const costs = Object.entries(handoff.expected_costs ?? {});
  const cheapest = costs.length ? Math.min(...costs.map(([, v]) => v)) : null;
  return (
    <Section id="handoff" title="Handoff package">
      <dl class="grid grid-cols-1 gap-x-6 gap-y-2 md:grid-cols-[max-content_1fr]">
        <dt class="font-semibold text-ink-muted">Asked</dt>
        <dd>{handoff.question}</dd>
        <dt class="font-semibold text-ink-muted">Understood</dt>
        <dd>{handoff.understanding}</dd>
        {handoff.rule_fired ? (
          <>
            <dt class="font-semibold text-ink-muted">Rule that fired</dt>
            <dd class="font-mono text-xs">{handoff.rule_fired}</dd>
          </>
        ) : null}
        <dt class="font-semibold text-ink-muted">Proof that settles it</dt>
        <dd>{handoff.resolving_proof ? humanize(handoff.resolving_proof) : <span class="text-ink-subtle">none named</span>}</dd>
        <dt class="font-semibold text-ink-muted">Suggested question</dt>
        <dd>{handoff.suggested_question ?? <span class="text-ink-subtle">none</span>}</dd>
      </dl>

      <div class="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Two leading hypotheses</h3>
          {(handoff.hypotheses ?? []).length === 0 ? (
            <p class="text-ink-subtle">None recorded.</p>
          ) : (
            <table class="w-full border-collapse">
              <tbody>
                {(handoff.hypotheses ?? []).slice(0, 2).map((h) => (
                  <tr key={h.label}>
                    <td class={TD}>{humanize(h.label)}</td>
                    <td class={`${TD} w-40`}>
                      <ConfBar value={h.probability} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          <h3 class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Unsure about</h3>
          {(handoff.uncertain_fields ?? []).length === 0 ? (
            <p class="text-ink-subtle">Nothing flagged.</p>
          ) : (
            <table class="w-full border-collapse">
              <thead>
                <tr>
                  <Th>Field</Th>
                  <Th>Value</Th>
                  <Th>Confidence</Th>
                  <Th>Why</Th>
                </tr>
              </thead>
              <tbody>
                {(handoff.uncertain_fields ?? []).map((f) => (
                  <tr key={f.field}>
                    <td class={`${TD} font-mono text-xs`}>{f.field}</td>
                    <td class={TD}>{f.value === null || f.value === undefined ? <span class="text-ink-subtle">unknown</span> : String(f.value)}</td>
                    <td class={TD}>
                      <ConfBar value={f.confidence} />
                    </td>
                    <td class={TD}>{humanize(f.why)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {costs.length > 0 ? (
        <p class="mt-3 text-xs text-ink-muted">
          Expected cost (units):{' '}
          {costs.map(([k, v]) => (
            <span key={k} class="me-3 font-mono">
              {k} {num(v, 1)}
              {v === cheapest ? ' (lowest)' : ''}
            </span>
          ))}
        </p>
      ) : null}
      {(handoff.guards ?? []).length > 0 ? (
        <p class="mt-1 text-xs text-ink-muted">
          Guards: {(handoff.guards ?? []).map((g) => (
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
          <pre class="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-2 font-mono text-xs">
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
