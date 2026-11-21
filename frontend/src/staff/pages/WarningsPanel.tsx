import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { BTN, BTN_DANGER, BTN_PRIMARY, flashFail, FlashLine, type Flash } from '../kit';
import { ALL_DISTRICTS, type WarningOut } from '../scam';
import { Badge, fmtTime, INPUT, Mono, Section, useLoad } from '../ui';

export interface WarningDraft {
  title: string;
  body_en: string;
  district: string;
  cluster_id: string | null;
  /** What this draft is about, shown above the form. */
  about: string;
}

export const emptyDraft: WarningDraft = { title: '', body_en: '', district: '', cluster_id: null, about: 'A district or a campaign' };

/** Publish a public warning in English and Urdu. Everything typed here is sent as text; the Urdu box is right-to-left. */
export function WarningForm({ draft, onChange, onPublished, onClose }: { draft: WarningDraft; onChange: (d: WarningDraft) => void; onPublished: () => void; onClose: () => void }) {
  const [bodyUr, setBodyUr] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const valid = draft.title.trim().length >= 5 && draft.body_en.trim().length >= 10 && (bodyUr.trim().length === 0 || bodyUr.trim().length >= 5);
  const submit = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(
      api.POST('/v1/scam/warnings', {
        body: {
          title: draft.title.trim(),
          body_en: draft.body_en.trim(),
          ...(bodyUr.trim() ? { body_ur: bodyUr.trim() } : {}),
          ...(draft.district ? { district: draft.district } : {}),
          ...(draft.cluster_id ? { cluster_id: draft.cluster_id } : {}),
        },
        params: { header: { 'Idempotency-Key': crypto.randomUUID() } },
      }),
    );
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: 'Warning published. Citizens in this department can see it now.' });
    setBodyUr('');
    onChange(emptyDraft);
    onPublished();
  };
  return (
    <form
      class="flex flex-col gap-2 border border-line-strong p-3"
      aria-label="Publish a public warning"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && !busy) void submit();
      }}
    >
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-sm font-semibold">Publish a public warning</h3>
        <button type="button" class={BTN} onClick={onClose}>
          Close
        </button>
      </div>
      <p class="text-xs text-ink-subtle">About: {draft.about}. Citizens see this text. Do not paste a phone number, a link or a name from a report.</p>
      <label class="flex flex-col gap-1">
        Title (English)
        <input class={INPUT} value={draft.title} maxLength={200} onInput={(e) => onChange({ ...draft, title: e.currentTarget.value })} />
      </label>
      <label class="flex flex-col gap-1">
        Message (English)
        <textarea class={`${INPUT} h-20 py-1`} value={draft.body_en} maxLength={1000} onInput={(e) => onChange({ ...draft, body_en: e.currentTarget.value })} />
      </label>
      <label class="flex flex-col gap-1">
        Message in Urdu (optional, right-to-left)
        <textarea class={`${INPUT} h-20 py-1 text-base`} dir="rtl" lang="ur" value={bodyUr} maxLength={1000} onInput={(e) => setBodyUr(e.currentTarget.value)} />
      </label>
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-1">
          District
          <select class={INPUT} value={draft.district} onChange={(e) => onChange({ ...draft, district: e.currentTarget.value })}>
            <option value="">Whole department</option>
            {ALL_DISTRICTS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {draft.cluster_id ? (
          <span class="text-xs text-ink-muted">
            Campaign <Mono>{draft.cluster_id.slice(0, 8)}</Mono>{' '}
            <button type="button" class="underline" onClick={() => onChange({ ...draft, cluster_id: null })}>
              detach
            </button>
          </span>
        ) : null}
        <button type="submit" class={BTN_PRIMARY} disabled={!valid || busy}>
          {busy ? 'Publishing…' : 'Publish warning'}
        </button>
      </div>
      <FlashLine flash={flash} />
    </form>
  );
}

/** Published warnings with a two-step withdraw. */
export function WarningList({ reloadKey, canWithdraw }: { reloadKey: number; canWithdraw: boolean }) {
  const [list, reload] = useLoad(() => call(api.GET('/v1/scam/warnings', { params: { query: { limit: 50 } } })), [reloadKey]);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const withdraw = async (w: WarningOut) => {
    setBusy(true);
    const res = await call(api.POST('/v1/scam/warnings/{warning_id}/withdraw', { params: { path: { warning_id: w.id } } }));
    setBusy(false);
    setConfirming(null);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: `Withdrawn: ${w.title}` });
    reload();
  };
  return (
    <Section id="warnings" title="Public warnings" aside={<button type="button" class={BTN} onClick={reload}>Refresh</button>}>
      <div class="flex flex-col gap-2">
        <FlashLine flash={flash} />
        {list.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading warnings…" /> : null}
        {list.state === 'fail' ? <FailureState failure={list.failure} density="staff" heading="h2" onRetry={reload} /> : null}
        {list.state === 'ok' && list.data.items.length === 0 ? <p class="text-ink-muted">No warnings published yet.</p> : null}
        {list.state === 'ok'
          ? list.data.items.map((w) => (
              <article key={w.id} class="border border-line p-2">
                <div class="flex flex-wrap items-center gap-2">
                  <h3 class="font-semibold">{w.title}</h3>
                  <Badge tone={w.status === 'published' ? 'warn' : 'neutral'}>{w.status}</Badge>
                  <span class="text-xs text-ink-subtle">{w.district ?? 'whole department'}</span>
                  <span class="font-mono text-xs text-ink-subtle">{fmtTime(w.published_at)}</span>
                  {canWithdraw && w.status === 'published' ? (
                    confirming === w.id ? (
                      <span class="ms-auto flex items-center gap-2">
                        <span class="text-xs">Remove it from citizens' screens?</span>
                        <button type="button" class={BTN_DANGER} disabled={busy} onClick={() => void withdraw(w)}>
                          Confirm withdraw
                        </button>
                        <button type="button" class={BTN} onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                      </span>
                    ) : (
                      <button type="button" class={`${BTN} ms-auto`} onClick={() => setConfirming(w.id)}>
                        Withdraw
                      </button>
                    )
                  ) : null}
                </div>
                <p class="mt-1 whitespace-pre-wrap">{w.body_en}</p>
                {w.body_ur ? (
                  <p class="mt-1 whitespace-pre-wrap text-base" dir="rtl" lang="ur">
                    {w.body_ur}
                  </p>
                ) : null}
              </article>
            ))
          : null}
      </div>
    </Section>
  );
}
