import { signal } from '@preact/signals';
import { onSessionEnd } from '../../shared/api/auth';
import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';
import type { MyScamReports, ScamCheckIn, ScamCheckOut, ScamDisputeOut } from '../../shared/api/types';
import type { Lang } from '../../shared/i18n';
import { newId } from '../../shared/ids';

/**
 * The scam checker's client state. Answers are kept in memory only (they
 * describe a message the person received), keyed by report and language, and
 * wiped when the session ends.
 */
const answers = new Map<string, ScamCheckOut>();
const keyOf = (id: string, code: Lang): string => `${id}:${code}`;

/** The message being written on the check screen; kept while the person looks at the answer. */
export const composeText = signal('');
export const composeSender = signal('');
/** True when the text came from speech and was not edited afterwards. */
export const composeSpoken = signal(false);
/** Set after "ask a person", so the answer screen can say thank you once. */
export const justDisputed = signal<string | null>(null);

onSessionEnd(() => {
  answers.clear();
  composeText.value = '';
  composeSender.value = '';
  composeSpoken.value = false;
  justDisputed.value = null;
});

export function cachedAnswer(id: string, code: Lang): ScamCheckOut | null {
  return answers.get(keyOf(id, code)) ?? null;
}

function remember(answer: ScamCheckOut): void {
  answers.set(keyOf(answer.report_id, answer.lang), answer);
}

let checkKey: { text: string; sender: string; key: string } | null = null;

/**
 * Check a message. One Idempotency-Key per message, so a retry after a lost
 * response returns the same report instead of a second one.
 */
export async function checkMessage(text: string, sender: string, spoken: boolean): Promise<Result<ScamCheckOut>> {
  const trimmed = text.trim().slice(0, 2000);
  const from = sender.trim().slice(0, 64);
  if (!checkKey || checkKey.text !== trimmed || checkKey.sender !== from) checkKey = { text: trimmed, sender: from, key: newId() };
  const body: ScamCheckIn = { text: trimmed, channel: spoken ? 'voice' : 'text' };
  if (from) body.sender = from;
  const result = await call(api.POST('/v1/scam/check', { body, headers: { 'Idempotency-Key': checkKey.key } }));
  if (result.ok) remember(result.data);
  return result;
}

export async function loadAnswer(id: string): Promise<Result<ScamCheckOut>> {
  const result = await call(api.GET('/v1/scam/reports/{report_id}', { params: { path: { report_id: id } } }));
  if (result.ok) remember(result.data);
  return result;
}

export function myChecks(cursor?: string): Promise<Result<MyScamReports>> {
  const query: { limit: number; cursor?: string } = { limit: 20 };
  if (cursor) query.cursor = cursor;
  return call(api.GET('/v1/scam/reports/mine', { params: { query } }));
}

/** "This is real, ask a person" (or "Ask a person" when we were not sure): opens a case for an officer. */
export async function askPerson(answer: ScamCheckOut, note: string): Promise<Result<ScamDisputeOut>> {
  const trimmed = note.trim().slice(0, 500);
  const result = await call(
    api.POST('/v1/scam/reports/{report_id}/dispute', {
      params: { path: { report_id: answer.report_id } },
      body: trimmed ? { note: trimmed } : {},
    }),
  );
  if (result.ok) {
    // Every cached language of this report now waits for a person.
    for (const [key, cached] of answers) {
      if (cached.report_id !== answer.report_id) continue;
      answers.set(key, { ...cached, can_dispute: false, review: { ...cached.review, status: 'waiting', case_id: result.data.case_id } });
    }
    justDisputed.value = answer.report_id;
  }
  return result;
}
