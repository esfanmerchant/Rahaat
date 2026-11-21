/** Turns a rule expression (JSON data, never code) into plain words. Display only. */

type Json = unknown;

const VAR_WORDS: Record<string, string> = {
  identity_verified: 'identity is verified',
  verified_income_pkr: 'verified monthly income',
  receives_other_aid: 'the person gets other aid',
  is_widow: 'the person is a widow',
  has_disability: 'the person has a disability',
  household_size: 'household size',
  age_years: 'age in years',
  district: 'district',
  gender: 'gender',
};

const CMP: Record<string, string> = { '==': 'is', '!=': 'is not', '<': 'is less than', '<=': 'is at most', '>': 'is more than', '>=': 'is at least' };
const ARITH: Record<string, string> = { '+': 'plus', '-': 'minus', '*': 'times', '/': 'divided by' };

const isObj = (v: Json): v is Record<string, Json> => typeof v === 'object' && v !== null && !Array.isArray(v);

export function words(expr: Json, params: Record<string, unknown> = {}): string {
  if (typeof expr === 'boolean') return expr ? 'yes' : 'no';
  if (typeof expr === 'number') return String(expr);
  if (typeof expr === 'string') return `"${expr}"`;
  if (!isObj(expr)) return '(unreadable)';
  const keys = Object.keys(expr);
  const op = keys[0];
  if (keys.length !== 1 || op === undefined) return '(unreadable)';
  const arg = expr[op];
  if (op === 'var') return VAR_WORDS[String(arg)] ?? String(arg);
  if (op === 'param') {
    const name = String(arg);
    return name in params ? `${name.replace(/_/g, ' ')} (${String(params[name])})` : `${name.replace(/_/g, ' ')} (not set)`;
  }
  const list = Array.isArray(arg) ? arg : [arg];
  const w = (x: Json) => words(x, params);
  if (op === 'and' || op === 'or') return list.map((x) => (isObj(x) && ['and', 'or'].includes(Object.keys(x)[0] ?? '') ? `(${w(x)})` : w(x))).join(op === 'and' ? ' and ' : ' or ');
  if (op === 'not') return `not (${w(list[0])})`;
  if ((op === '==' || op === '!=') && typeof list[1] === 'boolean' && isObj(list[0]) && 'var' in list[0]) {
    const positive = (op === '==') === list[1];
    return positive ? w(list[0]) : `not (${w(list[0])})`;
  }
  if (op in CMP) return `${w(list[0])} ${CMP[op]} ${w(list[1])}`;
  if (op === 'in') return `${w(list[0])} is one of ${Array.isArray(list[1]) ? list[1].map((x) => w(x)).join(', ') : w(list[1])}`;
  if (op in ARITH) return `(${w(list[0])} ${ARITH[op]} ${w(list[1])})`;
  return `${op}(${list.map(w).join(', ')})`;
}
