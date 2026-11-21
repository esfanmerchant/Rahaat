/**
 * The simulator's calls to the demo relay (`/v1/demo/*`). The relay runs the same code as the keyed channel
 * (`/v1/channels/*`) with a server-side demo channel, so the browser never holds an API key. Plain fetch: the
 * relay is demo-only and is not part of the typed client.
 */

export interface Persona {
  name: string;
  msisdn: string;
  display: string;
  tracking_code: string | null;
  symbols: string[];
}

export interface PersonasOut {
  personas: Persona[];
  demo_pin: string;
  service_code: string;
}

export interface UssdReply {
  kind: 'CON' | 'END';
  text: string;
}

export interface SmsMessage {
  id: string;
  at: string;
  body: string;
  template: string;
}

export interface SmsOut {
  accepted: boolean;
  command: string;
  reply_sent: boolean;
  messages: SmsMessage[];
}

export type RelayFailure = 'offline' | 'unavailable' | 'busy' | 'error';

export class RelayError extends Error {
  readonly kind: RelayFailure;
  constructor(kind: RelayFailure) {
    super(kind);
    this.kind = kind;
  }
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    });
  } catch {
    throw new RelayError('offline');
  }
  if (response.status === 404) throw new RelayError('unavailable'); // not in demo mode
  if (response.status === 429) throw new RelayError('busy');
  if (!response.ok) throw new RelayError('error');
  try {
    return (await response.json()) as T;
  } catch {
    throw new RelayError('error');
  }
}

export const loadPersonas = (): Promise<PersonasOut> => send('/v1/demo/ussd/personas');

export const dial = (sessionId: string, msisdn: string, text: string): Promise<UssdReply> =>
  send('/v1/demo/ussd', { method: 'POST', body: JSON.stringify({ session_id: sessionId, msisdn, text, service_code: '*786#' }) });

export const textIn = (msisdn: string, text: string, messageId: string): Promise<SmsOut> =>
  send('/v1/demo/sms', { method: 'POST', body: JSON.stringify({ msisdn, text, message_id: messageId }) });

export const loadThread = (msisdn: string): Promise<SmsMessage[]> => send(`/v1/demo/sms?msisdn=${encodeURIComponent(msisdn)}`);

/** A fresh id for a session or a text message. */
export function freshId(prefix: string): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `${prefix}-${[...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')}`;
}
