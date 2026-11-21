/**
 * Mock phone numbers only: 0999-NNNNNNN (CLAUDE.md non-negotiables). The
 * prefix is fixed in the UI, so a real number cannot be typed into this app.
 */
export const MOCK_PHONE_PREFIX = '0999';
export const MOCK_PHONE_LOCAL_DIGITS = 7;
export const PIN_MIN = 4;
export const PIN_MAX = 6;

export function mockPhone(local: string): string {
  return `${MOCK_PHONE_PREFIX}-${local}`;
}

export function isCompleteLocal(local: string): boolean {
  return new RegExp(`^\\d{${MOCK_PHONE_LOCAL_DIGITS}}$`).test(local);
}

export function isValidPin(pin: string): boolean {
  return /^\d+$/.test(pin) && pin.length >= PIN_MIN && pin.length <= PIN_MAX;
}
