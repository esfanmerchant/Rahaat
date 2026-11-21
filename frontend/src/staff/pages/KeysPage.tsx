import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import type { components } from '../../shared/api/schema';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_DANGER, BTN_PRIMARY, copyText, flashFail, FlashLine, ReasonAction, type Flash } from '../kit';
import { Badge, fmtTime, INPUT, Mono, Section, TD, Th, useLoad } from '../ui';

type Key = components['schemas']['ApiKeyOut'];
type Scope = components['schemas']['ScopeOut'];
type Created = components['schemas']['ApiKeyCreated'];

const TONE = { active: 'good', pending_approval: 'warn', revoked: 'bad', expired: 'neutral' } as const;

/** API keys for the department's partners. The secret is shown once; personal-data scopes wait for a second admin. */
export function KeysPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const [keys, reload] = useLoad(() => call(api.GET('/v1/admin/api-keys')), []);
  const [scopes] = useLoad(() => call(api.GET('/v1/admin/api-keys/scopes')), []);
  const [shown, setShown] = useState<Created | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  return (
    <section aria-labelledby="page-title" class="flex flex-col gap-3">
      <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
        API keys
      </h1>
      {shown ? <OnceBox created={shown} onDone={() => setShown(null)} /> : null}
      <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Section id="keys" title="Keys of this department">
          {keys.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading keys…" /> : null}
          {keys.state === 'fail' ? <FailureState failure={keys.failure} density="staff" heading="h2" onRetry={reload} /> : null}
          {keys.state === 'ok' && keys.data.length === 0 ? <ScreenState kind="empty" density="staff" title="No API keys" body="Create a key for a partner system. Every key expires." /> : null}
          {keys.state === 'ok' && keys.data.length > 0 ? (
            <div class="overflow-auto">
              <table class="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Prefix</Th>
                    <Th>Status</Th>
                    <Th>Scopes</Th>
                    <Th>Expires</Th>
                    <Th>Last used</Th>
                    <Th>Manage</Th>
                  </tr>
                </thead>
                <tbody>
                  {keys.data.map((k) => (
                    <tr key={k.id} class={sel === k.id ? 'bg-sunken' : ''}>
                      <td class={TD}>{k.name}</td>
                      <td class={TD}>
                        <Mono>{k.prefix}</Mono>
                      </td>
                      <td class={TD}>
                        <Badge tone={TONE[k.status]}>{k.status.replace('_', ' ')}</Badge>
                      </td>
                      <td class={`${TD} text-xs`}>{(k.status === 'pending_approval' ? k.requested_scopes : k.scopes)?.join(', ') || 'none'}</td>
                      <td class={TD}>{fmtTime(k.expires_at)}</td>
                      <td class={TD}>{k.last_used_at ? fmtTime(k.last_used_at) : 'never'}</td>
                      <td class={TD}>
                        <button type="button" class="underline" onClick={() => setSel(k.id)}>
                          Manage
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {sel && keys.state === 'ok' ? <Manage k={keys.data.find((x) => x.id === sel)} onDone={reload} onCreated={setShown} /> : null}
        </Section>
        <Section id="new" title="Create a key">
          {scopes.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading scopes…" /> : null}
          {scopes.state === 'fail' ? <FailureState failure={scopes.failure} density="staff" heading="h2" /> : null}
          {scopes.state === 'ok' ? (
            <Create
              scopes={scopes.data}
              onCreated={(c) => {
                setShown(c);
                reload();
              }}
            />
          ) : null}
        </Section>
      </div>
    </section>
  );
}

function OnceBox({ created, onDone }: { created: Created; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div role="alert" class="border border-warning-ink bg-warning-soft p-3" data-testid="key-once">
      <p class="font-semibold text-warning-ink">Copy this key now. It is shown once and only a hash is kept, so it cannot be shown again.</p>
      <p class="mt-1 flex flex-wrap items-center gap-2">
        <code class="break-all border border-line-strong bg-paper px-2 py-1 font-mono text-xs" data-testid="key-secret">
          {created.key}
        </code>
        <button
          type="button"
          class={BTN}
          onClick={() => {
            copyText(created.key);
            setCopied(true);
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" class={BTN} onClick={onDone}>
          I have stored it, hide it
        </button>
      </p>
      <p class="mt-1 text-xs text-ink-muted">
        {created.name}, expires {fmtTime(created.expires_at)}. {created.status === 'pending_approval' ? `It stays off until a second admin approves ${created.requested_scopes?.join(', ')}.` : 'It is active now.'}
      </p>
    </div>
  );
}

function Create({ scopes, onCreated }: { scopes: Scope[]; onCreated: (c: Created) => void }) {
  const [name, setName] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [days, setDays] = useState('90');
  const [rate, setRate] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const d = Number(days);
  const r = Number(rate);
  const valid = name.trim().length >= 3 && picked.length > 0 && Number.isInteger(d) && d >= 1 && d <= 365 && (rate === '' || (Number.isInteger(r) && r >= 1));
  const personal = scopes.filter((s) => picked.includes(s.name) && s.needs_second_admin);
  const create = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.POST('/v1/admin/api-keys', { body: { name: name.trim(), scopes: picked, expires_in_days: d, ...(rate !== '' ? { rate_limit_per_minute: r } : {}) } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setName('');
    setPicked([]);
    onCreated(res.data);
  };
  return (
    <form
      class="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && !busy) void create();
      }}
    >
      <label class="flex flex-col gap-1">
        Name (who uses it, at least 3 characters)
        <input class={INPUT} value={name} maxLength={120} onInput={(e) => setName(e.currentTarget.value)} />
      </label>
      <fieldset class="flex flex-col gap-1 border border-line p-2">
        <legend class="px-1 text-xs font-semibold uppercase text-ink-muted">Scopes</legend>
        {scopes.map((s) => (
          <label key={s.name} class="flex items-start gap-2">
            <input type="checkbox" class="mt-1" checked={picked.includes(s.name)} onChange={(e) => setPicked(e.currentTarget.checked ? [...picked, s.name] : picked.filter((x) => x !== s.name))} />
            <span>
              <span class="font-mono">{s.name}</span> {s.personal_data ? <Badge tone="warn">personal data, second admin</Badge> : null}
              <span class="block text-xs text-ink-muted">{s.description}</span>
              <span class="block font-mono text-xs text-ink-subtle">{s.endpoints.join(', ') || 'no endpoints yet'}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div class="flex flex-wrap gap-3">
        <label class="flex flex-col gap-1">
          Expires in days (1 to 365)
          <input class={`${INPUT} w-24`} inputMode="numeric" value={days} onInput={(e) => setDays(e.currentTarget.value)} />
        </label>
        <label class="flex flex-col gap-1">
          Requests a minute (optional)
          <input class={`${INPUT} w-28`} inputMode="numeric" value={rate} onInput={(e) => setRate(e.currentTarget.value)} />
        </label>
      </div>
      {personal.length > 0 ? <p class="text-xs text-warning-ink">{personal.map((s) => s.name).join(', ')} reads personal data. The key will not work until a second admin approves it.</p> : null}
      <div>
        <button type="submit" class={BTN_PRIMARY} disabled={!valid || busy}>
          {busy ? 'Creating…' : 'Create key'}
        </button>
      </div>
      <FlashLine flash={flash} />
    </form>
  );
}

function Manage({ k, onDone, onCreated }: { k: Key | undefined; onDone: () => void; onCreated: (c: Created) => void }) {
  const [mode, setMode] = useState<'rotate' | 'revoke' | 'approve' | 'refuse' | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  if (!k) return null;
  const act = async (reason: string) => {
    if (!mode) return;
    setBusy(true);
    setFlash(null);
    const params = { params: { path: { key_id: k.id } } };
    if (mode === 'rotate') {
      const res = await call(api.POST('/v1/admin/api-keys/{key_id}/rotate', { ...params, body: { reason } }));
      setBusy(false);
      if (!res.ok) return setFlash(flashFail(res.failure));
      onCreated(res.data);
    } else if (mode === 'revoke') {
      const res = await call(api.POST('/v1/admin/api-keys/{key_id}/revoke', { ...params, body: { reason } }));
      setBusy(false);
      if (!res.ok) return setFlash(flashFail(res.failure));
      setFlash({ tone: 'ok', text: 'Revoked. The key fails on its very next request.' });
    } else {
      const res = await call(api.POST('/v1/admin/api-keys/{key_id}/decide', { ...params, body: { approve: mode === 'approve', reason } }));
      setBusy(false);
      if (!res.ok) return setFlash(flashFail(res.failure));
      setFlash({ tone: 'ok', text: mode === 'approve' ? 'Approved. The scopes are on.' : 'Refused. The key stays without those scopes.' });
    }
    setMode(null);
    onDone();
  };
  return (
    <div class="mt-3 flex flex-col gap-2 border-t border-line pt-2">
      <h3 class="font-semibold">
        {k.name} <Mono>{k.prefix}</Mono>
      </h3>
      <div class="flex flex-wrap gap-2">
        {k.status === 'active' ? (
          <button type="button" class={BTN} onClick={() => setMode('rotate')}>
            Rotate
          </button>
        ) : null}
        {k.status === 'active' || k.status === 'pending_approval' ? (
          <button type="button" class={BTN_DANGER} onClick={() => setMode('revoke')}>
            Revoke
          </button>
        ) : null}
        {k.status === 'pending_approval' ? (
          <>
            <button type="button" class={BTN_PRIMARY} onClick={() => setMode('approve')}>
              Approve scopes (second admin)
            </button>
            <button type="button" class={BTN} onClick={() => setMode('refuse')}>
              Refuse
            </button>
          </>
        ) : null}
        {k.status === 'revoked' || k.status === 'expired' ? <span class="text-ink-muted">This key is {k.status}. Nothing more to do.</span> : null}
      </div>
      {k.status === 'pending_approval' ? <p class="text-xs text-ink-subtle">The admin who created the key cannot approve it. The server refuses that with a clear message.</p> : null}
      {mode ? <ReasonAction label={{ rotate: 'Rotate key', revoke: 'Revoke key', approve: 'Approve', refuse: 'Refuse' }[mode]} tone={mode === 'revoke' ? 'danger' : 'primary'} busy={busy} onSubmit={(r) => void act(r)} onCancel={() => setMode(null)} /> : null}
      <FlashLine flash={flash} />
    </div>
  );
}
