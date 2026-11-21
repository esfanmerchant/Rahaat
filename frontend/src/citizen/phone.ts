/**
 * Mock phone numbers only (CLAUDE.md non-negotiables). The person sees and types `+92 9990000201`: the
 * country code is fixed in the UI, then ten digits that must start with 999, so a real number (+92 3xx)
 * cannot be entered. The server takes both forms; we send the canonical `0999-NNNNNNN`.
 * The helpers live in `shared/phone.ts`; this file keeps the citizen names and the PIN rules.
 */
import { canonicalPhone, checkPhone, COUNTRY_CODE, PHONE_DIGITS } from '../shared/phone';

export { formatPhone, normalizePhone, checkPhone } from '../shared/phone';
export type { PhoneCheck } from '../shared/phone';
export const SHOWN_PHONE_PREFIX = COUNTRY_CODE;
export const PHONE_LENGTH = PHONE_DIGITS;
export const PIN_MIN = 4;
export const PIN_MAX = 6;

/** The form the server takes: `0999-NNNNNNN` (throws unless the ten digits are a mock number). */
export function mockPhone(digits: string): string {
  return canonicalPhone(digits);
}

export function isCompleteLocal(digits: string): boolean {
  return checkPhone(digits) === 'ok';
}

export function isValidPin(pin: string): boolean {
  return /^\d+$/.test(pin) && pin.length >= PIN_MIN && pin.length <= PIN_MAX;
}
