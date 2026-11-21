/**
 * Phones in the owner's format: `+92 XXXXXXXXXX`. Mock numbers are `0999-NNNNNNN` on the wire and show as
 * `+92 999NNNNNNN`. Display only: a request always carries the canonical form. Masked values (`0999-***0201`) keep their mask.
 */
export function formatPhone(raw: string | null | undefined): string {
  if (!raw) return '';
  const s = raw.trim();
  const m = /^0?999[- ]?([0-9*]{7})$/.exec(s) ?? /^\+92[ -]?999([0-9*]{7})$/.exec(s);
  return m ? `+92 999${m[1]}` : s;
}

/** The canonical mock form the API expects, from either spelling. Anything else is returned unchanged. */
export function canonicalPhone(raw: string): string {
  const m = /^\+92[ -]?999([0-9]{7})$/.exec(raw.trim());
  return m ? `0999-${m[1]}` : raw;
}
