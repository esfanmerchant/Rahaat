/**
 * Phone numbers, Pakistan's format: the country code, a space, then ten digits (`+92 9990000201`).
 * This prototype accepts only mock numbers, and a mock number's ten digits start with `999`
 * (CLAUDE.md non-negotiables). A real mobile number (`+92 3xx ...`) is never accepted and never sent.
 * The server wants the canonical form `0999-NNNNNNN`; `canonicalPhone` makes it.
 *
 * Pure functions with no imports, so a plain Node script can test them (`phone.test.ts`).
 */
export const COUNTRY_CODE = '+92';
export const MOCK_BLOCK = '999';
export const PHONE_DIGITS = 10;

/** Digits only, at most ten, with the country code or trunk zero taken off. For typed or pasted text. */
export function normalizePhone(raw: string): string {
  let digits = raw.replace(/\D+/g, '');
  if (digits.startsWith('0092')) digits = digits.slice(4);
  else if (digits.startsWith('92') && digits.length > PHONE_DIGITS) digits = digits.slice(2);
  else if (digits.startsWith('0') && digits.length > PHONE_DIGITS - 1) digits = digits.slice(1);
  return digits.slice(0, PHONE_DIGITS);
}

export type PhoneCheck = 'ok' | 'incomplete' | 'not_mock';

/** ok: ten digits starting with 999. not_mock: starts with anything else (checked as soon as the first digits are typed). */
export function checkPhone(digits: string): PhoneCheck {
  const head = digits.slice(0, MOCK_BLOCK.length);
  if (head.length > 0 && !MOCK_BLOCK.startsWith(head)) return 'not_mock';
  if (digits.length < PHONE_DIGITS) return 'incomplete';
  return /^999\d{7}$/.test(digits) ? 'ok' : 'not_mock';
}

/** The form the server takes: `0999-NNNNNNN`. Throws for anything that is not a complete mock number. */
export function canonicalPhone(digits: string): string {
  if (checkPhone(digits) !== 'ok') throw new Error('not a mock phone number');
  return `0${MOCK_BLOCK}-${digits.slice(3)}`;
}

/**
 * Every phone is shown as `+92 9990000201`. Takes digits typed so far, a pasted number or the canonical
 * `0999-NNNNNNN`. A masked value from the server (it has no ten digits) is shown as it came.
 */
export function formatPhone(value: string): string {
  const digits = normalizePhone(value);
  if (digits.length === PHONE_DIGITS || /^\d*$/.test(value.replace(/[\s+-]/g, ''))) return `${COUNTRY_CODE} ${digits}`;
  return value;
}
