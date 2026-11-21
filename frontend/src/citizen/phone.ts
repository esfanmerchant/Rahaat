/**
 * Mock phone numbers only (CLAUDE.md non-negotiables). The person sees and types +92 999 NNNNNNN; the prefix
 * is fixed in the UI, so a real number (+92 3xx) cannot be typed into this app. The server takes both forms;
 * we send the local form 0999-NNNNNNN.
 */
export const MOCK_PHONE_PREFIX = '0999';
/** What the screen shows in front of the seven digits (Pakistan's country code, then the mock block). */
export const SHOWN_PHONE_PREFIX = '+92 999';
export const MOCK_PHONE_LOCAL_DIGITS = 7;
export const PIN_MIN = 4;
export const PIN_MAX = 6;

export function mockPhone(local: string): string {
  return `${MOCK_PHONE_PREFIX}-${local}`;
}

/** A mock phone as shown to people: +92 999 NNNNNNN. */
export function showPhone(local: string): string {
  return `${SHOWN_PHONE_PREFIX} ${local}`;
}

export function isCompleteLocal(local: string): boolean {
  return new RegExp(`^\\d{${MOCK_PHONE_LOCAL_DIGITS}}$`).test(local);
}

export function isValidPin(pin: string): boolean {
  return /^\d+$/.test(pin) && pin.length >= PIN_MIN && pin.length <= PIN_MAX;
}
