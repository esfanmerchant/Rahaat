/**
 * English strings. This file defines the set of message keys; every other
 * language must provide the same keys (ur is checked by the compiler).
 *
 * Citizen copy rules (docs/DESIGN.md): about grade 5, at most three short
 * sentences, no jargon. Each citizen key may have an audio file at
 * /audio/{lang}/{key}.mp3 that says the same thing.
 */
export const en = {
  lang_name: 'English',
  app_name: 'Rahat',
  program_name: 'Rahat (Prototype Relief Program)',
  program_tagline: 'Help to get the relief payment.',

  start_button: 'Start',
  start_hint: 'Tap the big green button to begin.',
  choose_language: 'Choose your language',

  listen: 'Listen',
  back: 'Back',
  next: 'Next',
  retry: 'Try again',
  go_start: 'Go to the start',
  sign_out: 'Sign out',

  state_loading: 'Please wait.',
  state_empty_title: 'Nothing here yet',
  state_empty_body: 'There is nothing to show right now.',
  state_error_title: 'Something went wrong',
  state_error_body: 'Please try again. If it happens again, ask a helper.',
  state_offline_title: 'No internet',
  state_offline_body: 'Connect to the internet, then try again.',
  state_denied_title: 'This page is not for you',
  state_denied_body: 'Your account cannot open this page. A person can help you.',
  state_not_found_title: 'Page not found',
  state_not_found_body: 'This page does not exist.',
  state_reference: 'Reference: {id}',
  offline_banner: 'No internet right now.',

  login_phone_title: 'Your phone number',
  login_phone_hint: 'Type your number with the number buttons.',
  login_phone_label: 'Phone number',
  login_phone_invalid: 'Type all 7 numbers after 0999.',
  login_pin_title: 'Your secret PIN',
  login_pin_hint: 'Type your PIN. It has 4 to 6 numbers. Do not show it to anyone.',
  login_pin_label: 'PIN',
  login_pin_progress: '{count} of 6 numbers typed',
  login_pin_too_short: 'The PIN needs at least 4 numbers.',
  login_checking: 'Checking. Please wait.',
  login_wrong: 'The phone number or PIN is not right. Please try again.',
  login_locked: 'Too many wrong tries. Wait a little and try again, or ask a helper.',
  login_change_phone: 'Change number',
  keypad_delete: 'Delete',
  keypad_done: 'Done',
  keypad_label: 'Number buttons',

  digit_0: 'zero',
  digit_1: 'one',
  digit_2: 'two',
  digit_3: 'three',
  digit_4: 'four',
  digit_5: 'five',
  digit_6: 'six',
  digit_7: 'seven',
  digit_8: 'eight',
  digit_9: 'nine',

  home_greeting: 'Hello, {name}',
  home_apply: 'Apply for Rahat',
  home_apply_hint: 'Answer a few short questions. You can listen to each one.',
} as const;

export type MessageKey = keyof typeof en;
export type Dict = { readonly [K in MessageKey]: string };
