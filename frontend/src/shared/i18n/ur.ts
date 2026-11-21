import type { Dict } from './en';

/**
 * Urdu strings. Plain, everyday Urdu (about grade 5). The compiler checks that
 * every English key is present. Numbers stay as 0-9 digits, as on phone keypads.
 */
export const ur: Dict = {
  lang_name: 'اردو',
  app_name: 'راحت',
  program_name: 'راحت (آزمائشی امدادی پروگرام)',
  program_tagline: 'امدادی رقم حاصل کرنے میں مدد۔',

  start_button: 'شروع کریں',
  start_hint: 'شروع کرنے کے لیے بڑا سبز بٹن دبائیں۔',
  choose_language: 'اپنی زبان چنیں',

  listen: 'سنیں',
  back: 'واپس',
  next: 'آگے',
  retry: 'دوبارہ کوشش کریں',
  go_start: 'شروع پر جائیں',
  sign_out: 'باہر نکلیں',

  state_loading: 'تھوڑا انتظار کریں۔',
  state_empty_title: 'ابھی یہاں کچھ نہیں ہے',
  state_empty_body: 'ابھی دکھانے کے لیے کچھ نہیں ہے۔',
  state_error_title: 'کچھ غلط ہو گیا',
  state_error_body: 'دوبارہ کوشش کریں۔ پھر بھی نہ ہو تو کسی مددگار سے پوچھیں۔',
  state_offline_title: 'انٹرنیٹ نہیں ہے',
  state_offline_body: 'انٹرنیٹ سے جڑیں، پھر دوبارہ کوشش کریں۔',
  state_denied_title: 'یہ صفحہ آپ کے لیے نہیں ہے',
  state_denied_body: 'آپ کا اکاؤنٹ یہ صفحہ نہیں کھول سکتا۔ کوئی شخص آپ کی مدد کر سکتا ہے۔',
  state_not_found_title: 'صفحہ نہیں ملا',
  state_not_found_body: 'یہ صفحہ موجود نہیں ہے۔',
  state_reference: 'حوالہ نمبر: {id}',
  offline_banner: 'ابھی انٹرنیٹ نہیں ہے۔',

  login_phone_title: 'آپ کا فون نمبر',
  login_phone_hint: 'نمبر والے بٹن دبا کر اپنا نمبر لکھیں۔',
  login_phone_label: 'فون نمبر',
  login_phone_invalid: '0999 کے بعد ساتوں ہندسے لکھیں۔',
  login_pin_title: 'آپ کا خفیہ پن کوڈ',
  login_pin_hint: 'اپنا پن کوڈ لکھیں۔ اس میں چار سے چھ ہندسے ہیں۔ یہ کسی کو نہ دکھائیں۔',
  login_pin_label: 'پن کوڈ',
  login_pin_progress: '6 میں سے {count} ہندسے لکھے گئے',
  login_pin_too_short: 'پن کوڈ میں کم سے کم چار ہندسے ہونے چاہییں۔',
  login_checking: 'جانچ ہو رہی ہے۔ تھوڑا انتظار کریں۔',
  login_wrong: 'فون نمبر یا پن کوڈ درست نہیں ہے۔ دوبارہ کوشش کریں۔',
  login_locked: 'بہت بار غلط ہو گیا۔ تھوڑی دیر بعد کوشش کریں، یا کسی مددگار سے پوچھیں۔',
  login_change_phone: 'نمبر بدلیں',
  keypad_delete: 'مٹائیں',
  keypad_done: 'ٹھیک ہے',
  keypad_label: 'نمبر والے بٹن',

  digit_0: 'صفر',
  digit_1: 'ایک',
  digit_2: 'دو',
  digit_3: 'تین',
  digit_4: 'چار',
  digit_5: 'پانچ',
  digit_6: 'چھ',
  digit_7: 'سات',
  digit_8: 'آٹھ',
  digit_9: 'نو',

  home_greeting: 'السلام علیکم، {name}',
  home_apply: 'راحت کے لیے درخواست دیں',
  home_apply_hint: 'چند چھوٹے سوالوں کے جواب دیں۔ آپ ہر سوال سن سکتے ہیں۔',
};
