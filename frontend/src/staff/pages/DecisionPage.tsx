import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { Button } from '../../shared/components/Button';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Badge, humanize, INPUT, Section, useLoad, type DecisionTrace, type DecisionUserView } from '../ui';
import { HashFacts, TraceView } from './parts';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** There is no decision list endpoint: auditors arrive from an audit row or a case, or paste an id. */
export function DecisionIndex() {
  const { route } = useLocation();
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [id, setId] = useState('');
  const [touched, setTouched] = useState(false);
  const valid = UUID.test(id.trim());
  return (
    <section aria-labelledby="page-title" class="flex max-w-2xl flex-col gap-3">
      <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
        Decisions
      </h1>
      <p class="text-ink-muted">
        Open a decision by its id. Decision ids appear in the <a href="/staff/audit?action=decision.">audit trail</a> (object id of a decision row) and on every case.
      </p>
      <form
        class="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          if (valid) route(`/staff/decisions/${id.trim()}`);
        }}
      >
        <label class="flex flex-col gap-1">
          Decision id
          <input
            class={`${INPUT} w-96 max-w-full font-mono`}
            value={id}
            aria-invalid={touched && !valid}
            autoComplete="off"
            spellcheck={false}
            onInput={(e) => setId(e.currentTarget.value)}
          />
        </label>
        <Button size="sm" type="submit">
          Open decision
        </Button>
      </form>
      {touched && !valid ? (
        <p role="alert" class="text-danger">
          That is not a decision id. It looks like 50000000-0000-4000-8000-000000000001.
        </p>
      ) : null}
    </section>
  );
}

export function DecisionPage({ id }: { id: string }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/decisions/{decision_id}', { params: { path: { decision_id: id } } })), [id]);

  if (loaded.state === 'loading') return <ScreenState kind="loading" density="staff" body="Loading the decision…" />;
  if (loaded.state === 'fail') return <FailureState failure={loaded.failure} density="staff" onRetry={reload} />;

  const body = loaded.data as { user_view?: DecisionUserView; trace?: DecisionTrace };
  const view = body.user_view;
  const trace = body.trace;
  if (!trace) {
    // Officers receive the citizen view only; an auditor always gets the trace.
    return <ScreenState kind="denied" density="staff" title="No trace for your role" body="The server returned the citizen view only. The full trace is for auditors." />;
  }

  return (
    <article aria-labelledby="page-title" class="flex flex-col gap-4">
      <header class="flex flex-col gap-1">
        <a href="/staff/decisions" class="text-xs">
          All decisions
        </a>
        <div class="flex flex-wrap items-center gap-3">
          <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
            Decision {trace.decision_id.slice(0, 8)}
          </h1>
          <Badge>{trace.outcome}</Badge>
          <Badge tone="info">{trace.route}</Badge>
          <a href={`/staff/audit?object_id=${encodeURIComponent(trace.decision_id)}`} class="text-xs">
            Audit rows for this decision
          </a>
        </div>
      </header>

      <Section id="hashes" title="Identity of this decision">
        <HashFacts trace={trace} />
      </Section>

      <div class="grid items-start gap-4 xl:grid-cols-[minmax(18rem,24rem)_1fr]">
        <Section id="citizen" title="What the citizen was told">
          {view ? (
            <div class="flex flex-col gap-2">
              <p class="text-xs text-ink-muted">
                Outcome <Badge>{view.outcome}</Badge> Language <span class="font-mono">{view.explanation.lang}</span>
              </p>
              <ol class="flex flex-col gap-1 ps-4">
                {view.explanation.sentences.map((s, i) => (
                  <li key={i} class="list-decimal">
                    {s}
                  </li>
                ))}
              </ol>
              {view.explanation.next_step ? <p>Next step: {view.explanation.next_step}</p> : null}
              <p class="text-xs text-ink-muted">
                Reason codes: {view.explanation.reason_codes.map((r) => <Badge key={r}>{humanize(r)}</Badge>)}
              </p>
              <p class="text-xs text-ink-subtle">
                {view.explanation.ask_a_person ? 'The citizen is offered a person to ask. ' : ''}Rule version {view.rule_version_no}, decided {view.decided_at}.
              </p>
            </div>
          ) : (
            <p class="text-ink-muted">The server did not return the citizen view.</p>
          )}
        </Section>
        <Section id="trace" title="Full trace">
          <TraceView trace={trace} />
        </Section>
      </div>

      <Section id="snapshot" title="Input snapshot">
        <p class="mb-1 text-xs text-ink-subtle">Identifiers are masked or hashed according to your access.</p>
        <pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words border border-line bg-sunken p-2 font-mono text-xs">{JSON.stringify(trace.input_snapshot, null, 2)}</pre>
      </Section>

      {trace.handoff ? (
        <Section id="handoff" title="Handoff package recorded with the decision">
          <p>{trace.handoff.understanding}</p>
        </Section>
      ) : null}

      <Section id="verify" title="Replay and verification">
        <p class="text-ink-muted">
          Replay of a decision from its snapshot has no endpoint yet, so there is no replay button. The chain check covers the audit trail that references this decision.
        </p>
        <p class="mt-2">
          <a href="/staff/audit">Open the audit explorer and verify the chain</a>
        </p>
      </Section>
    </article>
  );
}
