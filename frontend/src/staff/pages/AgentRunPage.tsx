import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { LoadView } from '../loadview';
import { Mono, useLoad } from '../ui';
import { RunView, useStaffRole } from './AgentPanel';

/** One assistant run on its own page. Admin and auditor reach it from the audit log and read it without the case text. */
export function AgentRunPage({ id }: { id: string }) {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const role = useStaffRole();
  const [loaded, reload] = useLoad(() => call(api.GET('/v1/agent/runs/{agent_run_id}', { params: { path: { agent_run_id: id } } })), [id]);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          Assistant run
        </h1>
        <Mono>{id}</Mono>
      </div>
      <LoadView state={loaded} reload={reload} what="this assistant run" rows={5}>
        {(run) => (
          <div class="flex flex-col gap-2">
            {role === 'officer' ? <a href={`/staff/cases/${run.case_id}`}>Open the case to approve or reject</a> : <p class="text-xs text-ink-subtle">Read-only. Only an officer can approve or reject a proposal.</p>}
            <RunView run={run} role={role} onChange={() => reload()} onReload={reload} />
          </div>
        )}
      </LoadView>
    </section>
  );
}
