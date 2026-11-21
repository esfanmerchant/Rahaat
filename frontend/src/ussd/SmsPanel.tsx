import { useEffect, useRef, useState } from 'preact/hooks';
import { freshId, loadThread, RelayError, textIn, type RelayFailure } from './relay';

interface Item {
  key: string;
  dir: 'in' | 'out';
  body: string;
}

const QUICK = ['STATUS', 'VERIFY', 'STOP', 'HELP'] as const;
const PIN_WORDS = /^(\s*(?:STOP|ROKEIN|ROKO|BAND)\s+)(\d+)/i;

/** A PIN is hidden on the screen as soon as it is sent. It is never kept. */
function shown(text: string): string {
  return text.replace(PIN_WORDS, (_, head: string, pin: string) => head + '•'.repeat(pin.length));
}

const FAILURE: Record<RelayFailure, string> = {
  offline: 'No network. Check your connection and send again.',
  unavailable: 'The simulator is switched off here (demo mode only).',
  busy: 'Too many messages. Wait a minute and send again.',
  error: 'The message did not go through. Send it again.',
};

/** The SMS thread of one mock number: what the system sent it, and a box to text the service. */
export function SmsPanel({ msisdn, display, trackingDigits, pin }: { msisdn: string; display: string; trackingDigits: string | null; pin: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<RelayFailure | null>(null);
  const [loaded, setLoaded] = useState(false);
  const seen = useRef(new Set<string>());
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    seen.current = new Set();
    setItems([]);
    setLoaded(false);
    setFailure(null);
    loadThread(msisdn)
      .then((messages) => {
        if (!alive) return;
        for (const m of messages) seen.current.add(m.id);
        setItems(messages.map((m) => ({ key: m.id, dir: 'in', body: m.body })));
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setFailure(error instanceof RelayError ? error.kind : 'error');
        setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [msisdn]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' });
  }, [items.length]);

  async function send(text: string) {
    const body = text.trim();
    if (!body || busy) return;
    setBusy(true);
    setFailure(null);
    const mine: Item = { key: freshId('out'), dir: 'out', body: shown(body) };
    setItems((list) => [...list, mine]);
    setDraft('');
    try {
      const out = await textIn(msisdn, body, freshId('sim-sms'));
      const fresh = out.messages.filter((m) => !seen.current.has(m.id));
      for (const m of fresh) seen.current.add(m.id);
      setItems((list) => [...list, ...fresh.map((m): Item => ({ key: m.id, dir: 'in', body: m.body }))]);
    } catch (error) {
      setFailure(error instanceof RelayError ? error.kind : 'error');
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  function quick(word: (typeof QUICK)[number]) {
    if (word === 'HELP') return void send('HELP');
    const hint = word === 'STATUS' ? (trackingDigits ? `STATUS ${trackingDigits}` : 'STATUS ') : word === 'STOP' ? 'STOP ' : 'VERIFY ';
    setDraft(hint);
    input.current?.focus();
  }

  return (
    <section aria-label={`Text messages for ${display}`} class="flex min-h-0 flex-col rounded-2xl border border-night-line bg-night-1/80 shadow-float">
      <header class="flex items-baseline justify-between gap-3 border-b border-night-line px-4 py-3">
        <h2 class="m-0 text-base font-bold">Text messages</h2>
        <p class="m-0 font-mono text-sm text-night-muted">{display}</p>
      </header>
      <div class="flex max-h-[22rem] min-h-[12rem] flex-1 flex-col gap-2 overflow-y-auto px-4 py-3 lg:max-h-[26rem]" role="log" aria-live="polite" aria-label="Messages">
        {!loaded ? <p class="m-0 text-sm text-night-muted">Loading…</p> : null}
        {loaded && items.length === 0 ? (
          <p class="m-0 text-sm text-night-muted">No messages yet. Send HELP to see how it works.</p>
        ) : null}
        {items.map((m) => (
          <p key={m.key} class={`m-0 ussd-bubble ${m.dir === 'in' ? 'ussd-bubble-in' : 'ussd-bubble-out'}`}>
            <span class="sr-only">{m.dir === 'in' ? 'Rahat: ' : 'You: '}</span>
            {m.body}
          </p>
        ))}
        <div ref={end} />
      </div>
      {failure ? (
        <p role="alert" class="m-0 border-t border-night-line px-4 py-2 text-sm text-madder-glow">
          {FAILURE[failure]}
        </p>
      ) : null}
      <div class="flex flex-wrap gap-2 border-t border-night-line px-4 pt-3">
        {QUICK.map((word) => (
          <button
            key={word}
            type="button"
            onClick={() => quick(word)}
            disabled={busy}
            class="min-h-12 rounded-lg border border-night-line bg-night-2 px-3.5 text-sm font-bold tracking-wide text-night-ink hover:border-noor focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor disabled:opacity-50"
          >
            {word}
          </button>
        ))}
      </div>
      <form
        class="flex gap-2 px-4 pb-4 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <label class="sr-only" for="ussd-sms-draft">
          Text to send to Rahat
        </label>
        <input
          id="ussd-sms-draft"
          ref={input}
          value={draft}
          maxLength={160}
          autoComplete="off"
          autoCapitalize="characters"
          spellcheck={false}
          onInput={(e) => setDraft((e.target as HTMLInputElement).value)}
          class="min-h-12 min-w-0 flex-1 rounded-lg border border-night-line bg-night px-3 font-mono text-base text-night-ink placeholder:text-night-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor"
          placeholder={trackingDigits ? `STATUS ${trackingDigits}` : 'STATUS 12345'}
        />
        <button
          type="submit"
          disabled={busy || draft.trim() === ''}
          class="min-h-12 rounded-lg border border-noor bg-night-3 px-4 text-sm font-bold text-noor hover:bg-night-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-noor disabled:opacity-50"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </form>
      <p class="m-0 border-t border-night-line px-4 py-2 text-xs text-night-muted">
        Demo PIN for STOP: <span class="font-mono text-night-ink">{pin}</span>. Words in Roman Urdu work too: HALAT, TASDEEQ, ROKEIN, MADAD.
      </p>
    </section>
  );
}
