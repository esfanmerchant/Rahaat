/**
 * DB-free checks for the phone helpers. Run: `node --experimental-strip-types src/shared/phone.test.ts`
 * (from `frontend/`). Throws on the first failure.
 */
// @ts-expect-error Node needs the .ts extension here; the app imports it without.
import { canonicalPhone, checkPhone, formatPhone, normalizePhone } from './phone.ts';

function eq(actual: unknown, expected: unknown, what: string): void {
  if (actual !== expected) throw new Error(`${what}: got ${JSON.stringify(actual)}, wanted ${JSON.stringify(expected)}`);
}

for (const pasted of ['+92 9990000201', '+92 999 0000201', '92 9990000201', '929990000201', '0999-0000201', '09990000201', '9990000201', '0092 999-0000201', ' (+92) 999 000 0201 ']) {
  eq(normalizePhone(pasted), '9990000201', `normalize ${pasted}`);
}
eq(normalizePhone('99900'), '99900', 'partial digits stay');
eq(normalizePhone('99900002019999'), '9990000201', 'at most ten digits');
eq(normalizePhone(''), '', 'empty');

eq(checkPhone('9990000201'), 'ok', 'valid mock');
eq(checkPhone('99900'), 'incomplete', 'partial mock');
eq(checkPhone(''), 'incomplete', 'empty');
eq(checkPhone('3001234567'), 'not_mock', 'real mobile number is refused');
eq(checkPhone('3'), 'not_mock', 'refused from the first digit');
eq(checkPhone('9981234567'), 'not_mock', '998 is not the mock block');
eq(checkPhone('99'), 'incomplete', '99 may still become 999');

eq(canonicalPhone('9990000201'), '0999-0000201', 'canonical');
let threw = false;
try {
  canonicalPhone('3001234567');
} catch {
  threw = true;
}
eq(threw, true, 'canonical refuses a real number');

eq(formatPhone('9990000201'), '+92 9990000201', 'format digits');
eq(formatPhone('0999-0000201'), '+92 9990000201', 'format canonical');
eq(formatPhone('+92 9990000201'), '+92 9990000201', 'format shown form');
eq(formatPhone('99900'), '+92 99900', 'format partial');
eq(formatPhone(''), '+92 ', 'format empty');
eq(formatPhone('•••••••0201'), '•••••••0201', 'masked stays as it came');
console.log('phone helpers: all checks passed');
