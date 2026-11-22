import { useEffect } from 'preact/hooks';
import { AudioPrompt } from '../shared/components/AudioPrompt';
import { Emblem } from '../shared/components/Emblem';
import { Seal } from '../shared/components/Seal';
import { t } from '../shared/i18n';
import { celebrate } from '../shared/feedback';
import { inbox, refreshInbox } from './Inbox';

interface Paid {
  amount: string | null;
  code: string | null;
}

/**
 * The amount and the verify code of the payment message. The API sends the amount only inside the message
 * text today (docs/REQUESTS.md asks for a field), so it is read as the first number of that message; if there
 * is none, no amount is shown rather than a guessed one.
 */
function readPaid(items: readonly { template: string; body: string; verify_code?: string | null }[]): Paid {
  const message = items.find((item) => item.template === 'payment_sent');
  if (!message) return { amount: null, code: null };
  const amount = /\d[\d,]*/.exec(message.body.replace(/^[^:：]*[:：]/, ''))?.[0] ?? null;
  return { amount, code: message.verify_code ?? null };
}

/**
 * The top of home once the money was sent: a night card with a noor glow, the amount and the code that
 * anyone can check in the message checker, inside the seal. Text only comes from keyed strings and the API.
 */
export function PaidCard() {
  // The payment message comes from the inbox (one fetch for the bell and this card).
  const items = inbox.value.items;
  const paid: Paid | null = items ? readPaid(items) : null;
  useEffect(() => {
    void refreshInbox(true);
    const id = window.setTimeout(celebrate, 600);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <section aria-labelledby="paid-title" class="rh-night-sky relative overflow-hidden rounded-2xl p-6 shadow-glow motion-safe:animate-pop lg:p-8">
      <div aria-hidden="true" class="rh-lattice-night absolute inset-0" />
      <span aria-hidden="true" class="rh-breathe absolute inset-0 bg-[radial-gradient(70%_90%_at_50%_0%,rgb(255_211_110/0.3),transparent_70%)]" />
      <div class="relative flex flex-col items-center gap-4 text-center sm:flex-row sm:text-start">
        <div class="flex flex-1 flex-col items-center gap-2 sm:items-start">
          <Emblem size={44} tone="night" />
          <h2 id="paid-title" class="text-2xl font-black text-noor">
            {t('paid_title')}
          </h2>
          {paid?.amount ? (
            <p class="rh-num text-4xl font-black text-night-ink" dir="auto">
              {t('paid_amount', { amount: paid.amount })}
            </p>
          ) : null}
          <p class="text-base text-night-muted">{t('paid_body')}</p>
          <AudioPrompt prompt="paid_title" tone="night" />
        </div>
        {paid?.code ? (
          <div class="flex flex-col items-center gap-2 text-noor">
            <Seal size={168} tone="night">
              <span class="rh-ltr font-mono text-lg font-black tracking-wider text-night-ink">{paid.code}</span>
            </Seal>
            <p class="max-w-44 text-sm text-night-muted">{t('paid_code_label')}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
