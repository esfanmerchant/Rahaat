import { useMemo, useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN } from '../kit';
import { Badge, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

interface Health {
  database?: string;
  env?: string;
  ai_profile?: string;
  providers?: Record<string, string>;
  contract_stubs?: boolean;
}
interface PolicyRow {
  method: string;
  path: string;
  policy: string;
  roles: string[];
  public: boolean;
  reason?: string | null;
}

/** What is running now, and the policy registry: every route and who may call it. */
export function HealthPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [health, reloadHealth] = useLoad(() => call(api.GET('/v1/system/health')), []);
  const [policies, reloadPolicies] = useLoad(() => call(api.GET('/v1/system/policies')), []);
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const rows = useMemo(() => {
    if (policies.state !== 'ok') return [];
    const needle = q.trim().toLowerCase();
    return (policies.data as unknown as PolicyRow[]).filter(
      (r) => (!role || (role === 'public' ? r.public : r.roles.includes(role))) && (!needle || `${r.method} ${r.path} ${r.policy} ${r.roles.join(' ')} ${r.reason ?? ''}`.toLowerCase().includes(needle)),
    );
  }, [policies, q, role]);

  const h = health.state === 'ok' ? (health.data as Health) : null;
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <div class="flex items-center gap-3">
        <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
          System health
        </h1>
        <button type="button" class={BTN} onClick={() => { reloadHealth(); reloadPolicies(); }}>
          Refresh
        </button>
      </div>

      <Section id="health-now" title="Running now">
        {health.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Checking the platform…" /> : null}
        {health.state === 'fail' ? <FailureState failure={health.failure} density="staff" heading="h2" onRetry={reloadHealth} /> : null}
        {h ? (
          <div class="flex flex-col gap-3">
            <dl class="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
              <div>
                <dt class="text-xs text-ink-subtle">Database</dt>
                <dd>
                  <Badge tone={h.database === 'ok' ? 'good' : 'bad'}>{h.database ?? 'unknown'}</Badge>
                </dd>
              </div>
              <div>
                <dt class="text-xs text-ink-subtle">Environment</dt>
                <dd>
                  <Mono>{h.env}</Mono>
                </dd>
              </div>
              <div>
                <dt class="text-xs text-ink-subtle">AI profile</dt>
                <dd>
                  <Mono>{h.ai_profile}</Mono>
                </dd>
              </div>
              <div>
                <dt class="text-xs text-ink-subtle">Contract stubs</dt>
                <dd>
                  <Badge tone={h.contract_stubs ? 'warn' : 'good'}>{h.contract_stubs ? 'on' : 'off'}</Badge>
                </dd>
              </div>
            </dl>
            <table class="w-full border-collapse text-sm">
              <caption class="px-2 py-1 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted">Active AI providers</caption>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>State</Th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(h.providers ?? {}).map(([k, v]) => (
                  <tr key={k}>
                    <td class={TD}>
                      <Mono>{k}</Mono>
                    </td>
                    <td class={TD}>
                      <Badge tone={v === 'missing' || v === 'down' ? 'warn' : 'neutral'}>{v}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Section>

      <Section id="policy-registry" title="Policy registry" aside={policies.state === 'ok' ? <span class="text-xs text-ink-muted">{rows.length} of {policies.data.length} routes</span> : null}>
        <div class="flex flex-col gap-2">
          <div class="flex flex-wrap items-center gap-3">
            <label class="flex items-center gap-1">
              Search
              <input type="search" class={`${INPUT} w-64`} value={q} onInput={(e) => setQ(e.currentTarget.value)} aria-label="Search routes, policies and roles" />
            </label>
            <label class="flex items-center gap-1">
              Who may call
              <select class={INPUT} value={role} onChange={(e) => setRole(e.currentTarget.value)}>
                <option value="">Anyone listed</option>
                {['citizen', 'helper', 'officer', 'admin', 'auditor', 'public'].map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <span class="text-xs text-ink-subtle">The server enforces every one of these. This table only shows them.</span>
          </div>
          {policies.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading the registry…" /> : null}
          {policies.state === 'fail' ? <FailureState failure={policies.failure} density="staff" heading="h2" onRetry={reloadPolicies} /> : null}
          {policies.state === 'ok' && rows.length === 0 ? <ScreenState kind="empty" density="staff" heading="h2" title="No routes match" body="Change the search or the role filter." /> : null}
          {rows.length > 0 ? (
            <div class="max-h-[32rem] overflow-auto border border-line">
              <table class="w-full border-collapse text-sm">
                <caption class="sr-only">Every route and who may call it</caption>
                <thead>
                  <tr>
                    <Th>Method</Th>
                    <Th>Path</Th>
                    <Th>Policy</Th>
                    <Th>Roles</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.method} ${r.path}`} class="hover:bg-sunken">
                      <td class={`${TD} font-mono text-xs`}>{r.method}</td>
                      <td class={TD}>
                        <Mono>{r.path}</Mono>
                      </td>
                      <td class={TD}>
                        <Mono>{r.policy}</Mono>
                      </td>
                      <td class={TD}>
                        {r.public ? (
                          <span>
                            <Badge tone="warn">public</Badge> <span class="text-xs text-ink-muted">{r.reason}</span>
                          </span>
                        ) : (
                          r.roles.map((x) => (
                            <span key={x} class="me-1">
                              <Badge>{x}</Badge>
                            </span>
                          ))
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </Section>
    </section>
  );
}
