import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { Badge, humanize, Section, useLoad, type DecisionTrace, type DecisionUserView } from '../ui';
import { ReplayBox } from './DecisionList';
import { HashFacts, TraceView } from './parts';

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
        <ReplayBox id={trace.decision_id} />
      </Section>
    </article>
  );
}
