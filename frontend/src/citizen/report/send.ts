import { api } from '../../shared/api/client';
import { call, type ApiFailure } from '../../shared/api/problem';
import type { AppealOp, ComplaintOp, Outcome } from '../apply/outbox';

/** A refusal that will not change on a retry (a closed window, no consent) leaves the queue; a weak network does not. */
function outcomeFor(failure: ApiFailure): Outcome {
  switch (failure.kind) {
    case 'offline':
      return { type: 'wait', why: 'offline' };
    case 'unauthenticated':
      return { type: 'wait', why: 'session' };
    case 'network':
    case 'server':
    case 'rate_limited':
      return { type: 'retry', failure };
    default:
      return { type: 'drop', failure };
  }
}

/** The outbox transport for the two new op kinds. The same Idempotency-Key goes with every try, so a lost answer never files twice. */
export async function sendReport(op: AppealOp | ComplaintOp): Promise<Outcome> {
  const headers = { 'Idempotency-Key': op.key };
  const result =
    op.kind === 'appeal'
      ? op.app
        ? await call(api.POST('/v1/appeals', { body: { application_id: op.app, reason: op.text }, headers }))
        : null
      : await call(api.POST('/v1/complaints', { body: { category: op.category, ...(op.text ? { details: op.text } : {}) }, headers }));
  if (!result) return { type: 'wait', why: 'create' };
  return result.ok ? { type: 'done', result: result.data } : outcomeFor(result.failure);
}
