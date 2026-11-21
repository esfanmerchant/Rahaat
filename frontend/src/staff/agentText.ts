/**
 * Plain words for the agent panel: tools, guard codes, planner reasons, and one-line summaries of read-step output.
 * Everything here returns text; the screens render it as text, never as HTML.
 */
import { humanize } from './ui';

export const TOOL_LABEL: Record<string, string> = {
  get_case: 'Read the case',
  get_handoff: 'Read the handoff package',
  explain_decision: 'Read the decision explanation',
  check_rules: 'Check the rules',
  find_duplicates: 'Look for duplicates',
  search_policy: 'Search the policy text',
  request_proof: 'Ask the citizen for a proof',
  send_template_message: 'Send a template message',
  approve_and_pay: 'Approve and pay',
  reject_with_reason: 'Reject the application',
  escalate: 'Escalate to a senior officer',
};

export const toolLabel = (tool: string): string => TOOL_LABEL[tool] ?? humanize(tool);

/** What approving the step will do, in the words an officer needs before confirming. */
export const CONSEQUENCE: Record<string, string> = {
  request_proof: 'The case waits for the proof and the citizen gets the "proof needed" message.',
  send_template_message: 'The citizen gets the chosen template message. No free text is ever sent.',
  approve_and_pay: 'The application is approved and the payment is requested at the rule amount. Above the department limit a second officer must release it.',
  reject_with_reason: 'The application is rejected. The citizen is told a person checked it, and may appeal.',
  escalate: 'The case goes to a senior officer.',
};

/** The guard's reason codes (guardrails/action_guard.py) in plain words. */
export const BLOCK_TEXT: Record<string, string> = {
  unknown_tool: 'The tool is not on the allowed list.',
  tool_not_allowed_for_role: 'Your role may not use this tool.',
  case_state_invalid: 'The case or the application changed after the proposal, so this action no longer applies.',
  free_text_to_citizen: 'The action carried free text for the citizen. Only fixed templates may be sent.',
  amount_from_model: 'The action carried an amount or a payee. The amount comes from the rules, never from the assistant.',
  payment_without_approved_decision: 'The decision record and the rules do not support approving this payment.',
  reject_without_rule_failure: 'No hard rule failed on verified input, so a rejection is not supported.',
  step_budget_exceeded: 'The assistant used up its step budget.',
  step_already_run: 'This step already ran. It never runs twice.',
  no_approval: 'No officer approval was given.',
  self_approval: 'The approval must come from a signed-in officer, not from the assistant.',
  four_eyes_same_person: 'Above the payment limit the officer who already approved this case cannot approve it again. A different officer must.',
  proposal_blocked: 'The guard refused the first proposal, so the assistant stopped.',
};

export const blockText = (code: string): string => BLOCK_TEXT[code] ?? `The guard refused this step (${humanize(code)}).`;

const REASON_TEXT: Record<string, string> = {
  no_decision_trace: 'There is no decision record on this case yet.',
  signals_conflict: 'The signals disagree with each other.',
  rules_and_trace_support_approval: 'Every hard rule passed on verified input.',
  proposal_blocked: 'The guard refused a step.',
  low_retrieval: 'The policy search found nothing close enough.',
};
export const reasonText = (code: string): string => REASON_TEXT[code] ?? humanize(code);

const rs = (n: unknown): string => (typeof n === 'number' ? `Rs ${n.toLocaleString('en-US')}` : 'n/a');
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : v === null || v === undefined ? 'none' : String(v));
const list = (v: unknown): string => (arr(v).length ? arr(v).map(str).map(humanize).join(', ') : 'none');

type Out = Record<string, unknown>;

/** One short line for a read step, from its typed output. Unknown tools fall back to their key names. */
export function summarize(tool: string, o: Out): string {
  switch (tool) {
    case 'get_case':
      return `${humanize(str(o['kind']))}, status ${humanize(str(o['status']))}, ${str(o['note_count'])} note(s), opened because ${humanize(str(o['opened_reason']))}.`;
    case 'get_handoff': {
      const hyp = arr(o['hypotheses']) as Array<{ label?: string; probability?: number }>;
      const lead = hyp
        .slice(0, 2)
        .map((h) => `${humanize(str(h.label))} ${typeof h.probability === 'number' ? Math.round(h.probability * 100) : '?'}%`)
        .join(' vs ');
      return `${str(o['understanding'])}${lead ? ` Leading: ${lead}.` : ''}`;
    }
    case 'explain_decision': {
      const p = o['p_ok'];
      return o['route'] === null || o['route'] === undefined
        ? 'No decision record to explain yet.'
        : `Route ${str(o['route'])}, outcome ${humanize(str(o['outcome']))}, p_ok ${typeof p === 'number' ? p.toFixed(2) : 'n/a'}. Reasons: ${list(o['reasons'])}.`;
    }
    case 'check_rules': {
      const rules = arr(o['rules']);
      return `${rules.length} rule(s) checked. Hard rules failed: ${list(o['hard_failed'])}. Unknown: ${list(o['hard_unknown'])}. Payment ${rs(o['payment_pkr'])}. Approval ${o['approval_supported'] ? 'is' : 'is not'} supported.`;
    }
    case 'find_duplicates': {
      const c = arr(o['candidates']);
      return c.length === 0 ? 'No stored duplicate candidates.' : `${c.length} stored candidate(s), worst band ${str(o['worst_band'])}.`;
    }
    case 'search_policy': {
      if (!o['answered']) return `No confident match in the policy text (${reasonText(str(o['reason']))}). The assistant says so instead of guessing.`;
      const first = arr(o['sentences'])[0] as { text?: string } | undefined;
      return `${first?.text ?? 'Answered from the policy text.'} (${arr(o['citations']).length} citation(s))`;
    }
    default:
      return Object.keys(o).slice(0, 6).map(humanize).join(', ') || 'no output';
  }
}

/** The result of an approved action, from the step output. */
export function resultLine(o: Out): string {
  const bits: string[] = [];
  if (o['case_status']) bits.push(`case ${humanize(str(o['case_status']))}`);
  if (o['application_status']) bits.push(`application ${humanize(str(o['application_status']))}`);
  if (o['payment_status']) bits.push(`payment ${humanize(str(o['payment_status']))}${typeof o['payment_pkr'] === 'number' ? ` (${rs(o['payment_pkr'])})` : ''}`);
  if (o['notification_template']) bits.push(`message ${humanize(str(o['notification_template']))} queued`);
  return bits.length ? bits.join(', ') : 'done';
}
