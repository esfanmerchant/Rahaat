# Rahat design reference (frontend)

Prototype. Not an official service. All identity, payment and data services are simulated.

The rules both frontend tracks follow. Citizen app (`frontend/src/citizen`, `frontend/src/shared`, Track D1); staff console (`frontend/src/staff`, Track D2). Change tokens, pictograms or shared components by request to D1.

## Users and reading level

- **Citizen**: a widow who cannot read, a shopkeeper, a helper with 40 families. A cheap Android phone, weak signal, often offline. Urdu by default (RTL), then Sindhi and English.
- Copy is grade 5: at most three short sentences, everyday words, no jargon, no marketing. Each string is a key in `shared/i18n/{en,ur,sd}.ts`; the compiler checks Urdu has every English key. Sindhi falls back to Urdu (`TODO(sd)`).
- Every citizen key can have a recording at `public/audio/{lang}/{key}.mp3` saying the same thing. Missing files fail silently: the Urdu file for Sindhi, then a device voice for that language if one exists, else silence.
- **Staff**: officers, admins, auditors on a laptop. English, LTR, dense.

## Tokens (`shared/tokens.css`, Tailwind `@theme`)

| Group | Tokens (utility names) |
|---|---|
| Surface | `paper` #fff, `surface` #f4f2ee, `sunken` #f7f7f5, `chrome` #22272e (staff bar) |
| Text | `ink` 16.9:1, `ink-muted` 9.3:1 (AAA; citizen body text uses only these two), `ink-subtle` 5.9:1 (staff metadata only) |
| Lines | `line` (dividers), `line-strong` 4.7:1 (input borders, controls) |
| Action | `primary` #0d5c3d (white text 8:1), `primary-strong`, `primary-soft` |
| Status | `danger`/`danger-soft`, `warning`/`warning-ink`/`warning-soft`, `info`/`info-strong`/`info-soft`, `focus` |
| Type | `text-xs` .75 to `text-3xl` 2.25rem; scaled 1.1x for Urdu and Sindhi; line height comes from the language |
| Touch | `min-h-tap` 48px (minimum), `min-h-tap-lg` 64px (answers, keypad), `min-h-tap-xl` 96px (start) |
| Shape | `rounded-sm/md/lg/full`, `max-w-phone` 30rem. Shadows and blurs are removed from the theme. |

Light theme only. Tailwind's default colour palette is removed: only the tokens above exist. Never: gradients, blobs, glass or blur, decorative shadows, emoji as icons, web fonts, icon packages.

## Pictograms (`shared/components/Pictogram.tsx`)

One hand-drawn set: 48x48 grid, 3px round strokes, `currentColor`. Names: `yes`, `no`, `speaker`, `back`, `forward`, `person-help` (a person will help), `document`, `payment`, `family`, `widow`, `disability`, `phone`, `warning`, `retry`, `offline`, `lock`, `person`, `delete`, `home`, `clock`, `camera`, `microphone`.

- Draw new ones on the same grid and stroke; add them to the set, not inline.
- `back`, `forward` and `delete` mirror in RTL. Inside an LTR island (keypad, phone number) pass `mirror={false}`: Tailwind's `rtl:` matches any RTL ancestor.
- Put a word next to the icon where there is room. Icon-only buttons need `aria-label`.

## Citizen rules

- One question per screen, one primary action, a way back (top bar, start side), a speaker button (top bar, end side) that plays the screen's prompt.
- The first screen has one large start button; its tap unlocks audio (browsers block sound before a tap). After that, prompts may auto-play.
- Tap targets at least 48px; answers and keys 64px. No typing needed to finish the application. Numbers use the keypad component.
- Never speak a PIN digit aloud. Phone digits may be spoken.
- Mock data only: phone fixed to `0999-` + 7 digits in the UI; IDs `00000-NNNNNNN-C`.
- Show detection details (why something was flagged) only in staff and auditor views. Citizens hear "a person will check".
- Render untrusted text (names, OCR, messages) as text, never as HTML. No `dangerouslySetInnerHTML`.
- Budget: citizen JS at most 100 KB gzip, aim for 60. `npm run check:bundle` fails the build above 100 KB or if staff code leaks into the citizen entry.

## Staff rules

- Dense and tabular: `text-sm`, `size="sm"` buttons (32px is fine on desktop), tables with sticky headers, no decorative chrome.
- Keyboard first: real links and buttons, visible focus, skip link, native `<select>`, `Enter` submits.
- Navigation comes from the role (`staff/nav.ts`) and is cosmetic: the server enforces access. Every page handles 403 with the permission-denied state.
- Unbuilt pages are dev placeholders marked `built: false`; build with `VITE_SHOW_UNBUILT=false` to hide them before the demo.
- Staff code lives in the lazy `staff` chunk; `/demo` in the lazy `demo` chunk. Never import `src/staff/**` from citizen or shared code.

## State checklist (every screen)

| State | What the person sees | Helper |
|---|---|---|
| Loading | spinner and "Please wait" (no blank screen, no layout jump) | `ScreenState kind="loading"` |
| Empty | what is missing and what to do next | `kind="empty"` |
| Error | plain message, Try again, `request_id` as a reference | `kind="error"`, `FailureState` |
| Offline | the network banner (always) plus what still works; never lose typed work | `NetworkBanner`, `kind="offline"` |
| Permission denied | "not for you", who can help; never hide the cause | `kind="denied"` |
| Not found | where to go instead | `kind="not_found"` |
| Success | the screen itself, with the next step | |

Wrap calls with `call(api.GET(...))` (`shared/api/problem.ts`): it never throws and maps failures to a kind. 401 is handled for you (one refresh, one retry); a session that cannot be refreshed signs the person out.

## RTL and language rules

- `<html lang dir>` follows the language signal. Use logical utilities only: `ms-/me-`, `ps-/pe-`, `start-/end-`, `text-start/end`, `border-s/e`. Never `ml-`, `pr-`, `left-`, `text-left`.
- Urdu font stack, from the device: `"Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "Noto Naskh Arabic", system-ui`. Sindhi puts Naskh first. Line height is at least 2 for Urdu and Sindhi; it is set per language, so do not use fixed `leading-*` or fixed heights on text (use `min-h-*` and padding).
- A run in another language gets its own `lang` and `dir` (for example the English footer line).
- Numbers, phones, PINs and IDs: Western digits, wrapped in `rh-ltr` (direction ltr, bidi isolate). `t()` wraps every `{param}` in Unicode isolates, so names and numbers do not scramble the sentence.

## Security rules in the client

- Access token in memory only (`shared/api/session.ts`). Never `localStorage`, `sessionStorage` or IndexedDB for tokens or personal data. The refresh token is an httpOnly cookie the script never sees; a reload calls `/v1/auth/refresh` once.
- Strict CSP (`script-src 'self'; style-src 'self'`): no inline scripts, `<style>` tags or `style="..."` in HTML. `npm run preview` sends the same policy.
- The service worker precaches the shell and audio only. It never caches an API response.
