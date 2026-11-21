import { session } from '../shared/api/auth';
import type { components } from '../shared/api/schema';

type S = components['schemas'];
export type MapOut = S['MapOut'];
export type TrendsOut = S['TrendsOut'];
export type CampaignOut = S['CampaignOut'];
export type ScamReportOut = S['ScamReportOut'];
export type ScamCheckOut = S['ScamCheckOut'];
export type WarningOut = S['WarningOut'];
export type ScamLabelName = S['LabelIn']['label'];

export const SCAM_KINDS = ['relief_scam', 'phishing_link', 'advance_fee', 'impersonation'] as const;

const LABEL_TEXT: Record<string, string> = {
  relief_scam: 'Fake relief offer',
  phishing_link: 'Phishing link',
  advance_fee: 'Advance fee',
  impersonation: 'Impersonation',
  legit_program_message: 'Genuine program message',
  unknown: 'Unknown',
};
export const labelText = (label: string): string => LABEL_TEXT[label] ?? label.replace(/_/g, ' ');
export const isScamKind = (label: string | null | undefined): boolean => !!label && (SCAM_KINDS as readonly string[]).includes(label);

/** Hand-drawn tile layout: each district is one square, grouped by province, roughly north at the top. */
export const SINDH_TILES: readonly (readonly (string | null)[])[] = [
  ['Kashmore', 'Jacobabad', 'Shikarpur', 'Ghotki', 'Sukkur', 'Khairpur', null],
  ['Qambar Shahdadkot', 'Larkana', 'Dadu', 'Naushahro Feroze', 'Shaheed Benazirabad', 'Sanghar', null],
  ['Jamshoro', 'Matiari', 'Hyderabad', 'Tando Allahyar', 'Tando Muhammad Khan', 'Mirpurkhas', null],
  ['Thatta', 'Sujawal', 'Badin', 'Umerkot', 'Tharparkar', null, null],
  ['Keamari', 'Karachi West', 'Karachi Central', 'Karachi South', 'Karachi East', 'Korangi', 'Malir'],
];
export const PUNJAB_TILES: readonly (readonly (string | null)[])[] = [
  ['Attock', 'Rawalpindi', 'Jhelum', 'Chakwal', 'Mianwali', 'Khushab'],
  ['Gujrat', 'Sialkot', 'Narowal', 'Gujranwala', 'Hafizabad', 'Mandi Bahauddin'],
  ['Lahore', 'Sheikhupura', 'Nankana Sahib', 'Kasur', 'Faisalabad', 'Chiniot'],
  ['Sargodha', 'Bhakkar', 'Jhang', 'Toba Tek Singh', 'Okara', 'Sahiwal'],
  ['Pakpattan', 'Khanewal', 'Multan', 'Lodhran', 'Vehari', 'Bahawalnagar'],
  ['Layyah', 'Muzaffargarh', 'Dera Ghazi Khan', 'Rajanpur', 'Bahawalpur', 'Rahim Yar Khan'],
];
export const ALL_DISTRICTS: readonly string[] = [...SINDH_TILES, ...PUNJAB_TILES].flat().filter((d): d is string => d !== null).sort();

/** Staff who may publish or withdraw warnings and set labels. The server decides; this only hides buttons. */
export function activeRole(): string {
  const s = session.value;
  return s.status === 'signed-in' ? s.active.role : '';
}

export const shortDay = (day: string): string => day.slice(5);
