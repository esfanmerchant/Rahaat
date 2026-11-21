import { useState } from 'preact/hooks';
import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { FailureState, ScreenState } from '../../shared/components/ScreenState';
import { useFocusOnMount } from '../../shared/useFocusOnMount';
import { BTN, BTN_PRIMARY, flashFail, FlashLine, MIN_REASON, type Flash } from '../kit';
import { activeRole } from '../scam';
import { INPUT, Section, useLoad } from '../ui';
import { CostSummary } from './CostPage';

const STANDARD_PAYMENT = 12_000;
const fmtRs = (n: number) => `Rs ${n.toLocaleString('en-US')}`;

/** Department settings. Admins change them; officers and auditors read them. The server decides who may write. */
export function SettingsPage() {
  const headingRef = useFocusOnMount<HTMLHeadingElement>();
  const canEdit = activeRole() === 'admin';
  const [settings, reload] = useLoad(() => call(api.GET('/v1/admin/payment-settings')), []);
  return (
    <section aria-labelledby="page-title" class="flex max-w-3xl flex-col gap-3">
      <h1 id="page-title" ref={headingRef} tabIndex={-1} class="text-lg font-semibold">
        Settings
      </h1>
      <Section id="four-eyes" title="Payment: second officer limit">
        {settings.state === 'loading' ? <ScreenState kind="loading" density="staff" body="Loading settings…" /> : null}
        {settings.state === 'fail' ? <FailureState failure={settings.failure} density="staff" heading="h2" onRetry={reload} /> : null}
        {settings.state === 'ok' ? <FourEyes limit={settings.data.four_eyes_limit_pkr} canEdit={canEdit} onSaved={reload} /> : null}
      </Section>
      <Section id="cost-matrix" title="Cost matrix">
        <CostSummary />
      </Section>
    </section>
  );
}

function FourEyes({ limit, canEdit, onSaved }: { limit: number; canEdit: boolean; onSaved: () => void }) {
  const [value, setValue] = useState(String(limit));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const n = Number(value);
  const validNum = value.trim() !== '' && Number.isInteger(n) && n >= 0 && n <= 1_000_000;
  const ok = validNum && reason.trim().length >= MIN_REASON && n !== limit;
  const everyPayment = (v: number) => v < STANDARD_PAYMENT;
  const save = async () => {
    setBusy(true);
    setFlash(null);
    const res = await call(api.PUT('/v1/admin/payment-settings', { body: { four_eyes_limit_pkr: n, reason: reason.trim() } }));
    setBusy(false);
    if (!res.ok) return setFlash(flashFail(res.failure));
    setFlash({ tone: 'ok', text: `Saved. The limit is now ${fmtRs(res.data.four_eyes_limit_pkr)}. The change is in the audit log.` });
    setReason('');
    onSaved();
  };
  return (
    <div class="flex flex-col gap-3">
      <p>
        A payment above this limit must be released by a second officer, never the one who prepared it. The standard relief payment is {fmtRs(STANDARD_PAYMENT)}, so with a limit below {fmtRs(STANDARD_PAYMENT)} every standard payment needs a second officer.
      </p>
      <dl class="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <div>
          <dt class="text-xs text-ink-subtle">Current limit</dt>
          <dd class="text-2xl font-semibold tabular-nums" data-testid="four-eyes-limit">
            {fmtRs(limit)}
          </dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Effect now</dt>
          <dd>{everyPayment(limit) ? `Every standard ${fmtRs(STANDARD_PAYMENT)} payment needs a second officer.` : `A standard ${fmtRs(STANDARD_PAYMENT)} payment can be released by one officer.`}</dd>
        </div>
      </dl>
      {canEdit ? (
        <form
          class="flex flex-col gap-2 border border-line p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (ok && !busy) void save();
          }}
        >
          <label class="flex flex-wrap items-center gap-2">
            New limit (Rs)
            <input class={`${INPUT} w-36 font-mono`} inputMode="numeric" value={value} onInput={(e) => setValue(e.currentTarget.value)} aria-invalid={!validNum} />
            <span class="text-xs text-ink-subtle">0 to 1,000,000</span>
          </label>
          {validNum ? <p class="text-xs text-ink-muted">{everyPayment(n) ? `At ${fmtRs(n)}, every standard payment needs a second officer.` : `At ${fmtRs(n)}, a standard payment needs only one officer.`}</p> : <p class="text-xs text-danger">Enter a whole number from 0 to 1,000,000.</p>}
          <label class="flex flex-col gap-1">
            Reason (audit log, at least {MIN_REASON} characters)
            <input class={INPUT} value={reason} maxLength={500} onInput={(e) => setReason(e.currentTarget.value)} />
          </label>
          <div class="flex items-center gap-2">
            <button type="submit" class={BTN_PRIMARY} disabled={!ok || busy}>
              {busy ? 'Saving…' : 'Save limit'}
            </button>
            <button type="button" class={BTN} onClick={() => { setValue(String(limit)); setReason(''); }}>
              Reset
            </button>
          </div>
        </form>
      ) : (
        <p class="text-xs text-ink-subtle">Only an admin can change this. You can read it.</p>
      )}
      <FlashLine flash={flash} />
    </div>
  );
}
