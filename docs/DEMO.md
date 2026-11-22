# Live demo script (6 to 7 minutes)

**Prototype. Not an official service. All identity, payment and data services are simulated.**

Primary URL: **https://rahat-zeta.vercel.app**. Backup URL: given at the demo (a Cloudflare quick tunnel to a PC; the address changes when it restarts). The accounts are on the `/demo` page, which signs in with one tap. Written out:

| Who | Sign in | Secret |
|---|---|---|
| Zainab Bibi, widow (citizen, Urdu) | phone `0999-0000201` | PIN `4826` |
| Aslam Khan, shopkeeper (citizen) | phone `0999-0000202` | PIN `4826` |
| Rubina Shaikh, community helper | phone `0999-0000101` | PIN `4826` |
| Officer Farhan Qureshi | `officer@sindh.rahat.example` | `Rahat-Demo-2026!` |
| Auditor Nadia Hussain | `auditor@rahat.example` | `Rahat-Demo-2026!` |
| Admin Ayesha Siddiqui; second admin Bilal Ahmed | `admin@sindh.rahat.example`, `approver@sindh.rahat.example` | `Rahat-Demo-2026!` |

Specimen cards for the camera step are on the **`/demo/kit`** page (download on the phone, or point the camera at the laptop screen), and in `data/demo_cards/<person>/`. Ten per person: three pass the card check, three ask for a new photo (blurry, glare on the QR, cut off), four go to a person (edited name, someone else's QR, unknown issuer, broken signature). Measured on 22 Nov: all 30 give that result, with or without OCR. They are generated and marked SPECIMEN.

**Roles.** Presenter drives the laptop. Second person holds the phone (citizen screens at phone width). Say each line in one or two sentences; let the screen do the rest.

**Before the demo (2 minutes):** reset to the clean state with `npm run seed -- --reset` on the PC host, or, for the Vercel database, `powershell -ExecutionPolicy Bypass -File deploy/vercel/reset-db.ps1 -Reset` on the PC that holds `.live/secrets.env` (about 5 minutes; every demo account comes back clean). Open `/demo` on the laptop. Check `/healthz` returns 200. Have two browser profiles: citizen and staff.

## The script

| Time | Who clicks what | Say | Judges should notice |
|---|---|---|---|
| 0:00 | Laptop: open the URL. Show the citizen start screen. Tap the language switch (English, Urdu). | "Rahat helps people who cannot read forms apply for and track a mock relief payment. It decides, explains, protects, and says 'I am not sure' and hands over to a person. Everything here is simulated." | Prototype label in the footer. Urdu and right-to-left layout. Big icons, one question per screen. |
| 0:30 | Phone: sign in as **Zainab** (`0999-0000201`, PIN). Start the application. Give consent. Answer one question by voice in Urdu; show the read-back; confirm. Answer the next by tapping an icon. | "Zainab cannot type. She answers by voice or by tapping pictures. Every spoken answer is read back and she confirms it, because speech recognition makes mistakes." | Audio prompts, read-back, no typing, consent screen before any data is taken. If the room is noisy, use icons only and say so. |
| 1:15 | Phone: take a photo of `blurry.jpg` as her card. Then `clean.jpg`. Submit. | "A blurry photo gets a spoken retake hint, not a rejection. The good photo is checked: the signed QR on the card is verified, and the printed text is compared with it." | Retake hint instead of failure. The citizen is never told why a document is suspicious; staff see that later. |
| 1:50 | Phone: the result screen. | "Zainab has no income record, so the system does not guess. It asks for one proof, then, since the evidence is still thin, it says 'a person will check'." | Outcome "needs proof", then "a person will check". Tracking symbol code. Three short sentences, English and Urdu. |
| 2:15 | Laptop (staff profile): sign in as **Officer**. Open the queue, then Zainab's case. | "The officer sees a handoff package first: what the system knows, what it does not, and its two best explanations." | Handoff package, not a raw score. Detection details appear here, for staff only. |
| 2:45 | Officer: approve with a reason. Show the payment (Rs 12,000, under the Rs 15,000 limit) and the outbox SMS with the verify code. | "The officer approves with a written reason. The payment is released through an approval gate, and the SMS carries a verify code." | Reason is required. Payment appears only after an approved decision. |
| 3:10 | Phone: sign in as **Aslam**. Apply with `clean.jpg`. Show the result. Open the SMS in the outbox, copy the verify code into the verify-a-message check. | "Aslam's case is clear: signed card, registry income. The system approves and pays alone, and his verify code checks out." | Auto-approved, paid Rs 12,000, "genuine" for the code. No person involved. |
| 3:40 | Phone, Aslam: open the scam checker. Paste the Roman Urdu relief scam (the Challenge Lab has ready text: "Congratulations! You are selected for Rahat relief Rs 25,000. Send Rs 500 fee ..."). Then the real message with its code. Then a short ambiguous one. | "Fake relief messages are the shopkeeper's real danger. It says scam, real, or not sure. Links are never clickable." | Three different answers, one of them "not sure". Pictogram answer read aloud. |
| 4:10 | Phone: sign in as **Rubina** (helper). Show the 40 families. Open one, enter that family's PIN. | "Rubina helps 40 families. Each family gives her access separately, and one tap revokes it." | List of 40 families. A family PIN is needed for each. A banner shows she is acting for someone. |
| 4:35 | Laptop: officer, Decisions, open Zainab's decision. Show the anatomy: facts, rules fired, probabilities, expected cost of each action, chosen route. | "Every decision shows why. Wrong approvals cost 100, a person's review 3, so the system approves alone only above 96.8% confidence." | Two views: plain reason for the citizen, full trace for staff. Expected cost per action. |
| 5:05 | Laptop: sign in as **Auditor**. Open the same decision, press Replay, then Verify chain in Audit. | "The auditor replays the stored decision from its snapshot and gets the identical result. The audit log is a hash chain, so editing a row is detected." | Replay equals the original. Chain verifies. |
| 5:35 | Laptop: open `/live`. | "This is the decision engine drawn from our synthetic evaluation set: 1,223 held-out cases routed under the same cost matrix. Most cases go to a person or a proof; very few are approved alone, and one ineligible person was approved." | The picture matches `docs/EVAL_REPORT.md`: 1 wrong approval, 5 wrong rejections, 25.5% automatic. (If `/live` is not deployed, show the staff Evaluation page instead.) |
| 6:00 | Laptop: staff console, Challenge Lab (staff, all roles). Run card 1 (cost of being wrong) and card 5 (explain and audit). | "Each card makes real API calls and shows the request, the response and the audit id." | Real requests and responses, not slides. |
| 6:30 | Close. | "Models are trained on synthetic data, so real accuracy is unknown. We list that, and what is simulated, in the README." | Honest limits. |

## Challenge Lab cards (staff console, `Challenge Lab`)

**Order matters (checked in Gate 2, Sat 21 Nov).** Cards 2, 5 and 6 read real decisions and applications, and card 4 compares the seeded draft rule v2 with v1. Right after a reset there are no decisions yet, so those cards answer "info". Run the citizen part first (Aslam and Zainab), then the Lab. All eight cards and the three security cards passed on the live URL in that order. Card 6 withdraws and re-grants Zainab's consent; it leaves her consent active.

Cards in the console include: cost of being wrong (three seeded cases: clear, borderline, fraud signal), I am not sure (queue and handoff package), bad data (Mohammad against Muhammed goes to "possible duplicate", garbage input returns a repairable 422), rules that change, explain and audit, consent take-back, scams and fakes, and a security strip. Check on the day which are live on the deployed build (the page marks unbuilt ones); do not run a card you have not run beforehand. The consent take-back card needs a seeded citizen with a live consent; the security card's live probes pass on both hosts (migration 0006 fixed finding 2), but rehearse it first like every card.

## If the network fails

1. **Phone hotspot** for the laptop. Try the primary URL again.
2. **PC backup.** The PC at the venue runs the same app on an embedded PostgreSQL behind a Cloudflare quick tunnel: `npm run live:status` prints the URL, `npm run live:start` starts it, `npm run live:reset` returns it to the clean demo state. Or open `http://127.0.0.1:8080` on the PC itself, which needs no internet. Everything works there except that the tunnel is not reachable by others. This host also has OCR, so the printed-text check runs.
3. **Screenshots.** A folder of screenshots of each step above, plus the demo video, on the laptop and on Drive. Narrate the same lines.

Differences to know: on Vercel there is no OCR (function size limit), so only the signed-QR check runs; the first request after idle can take a few seconds (cold start); data is shared by everyone, so use **Reset** if a judge has changed the cases.

## 60-second version

1. (0:00) Open the URL. "Rahat is a multi-tenant platform that helps people who cannot read forms apply for a mock relief payment, and says 'I am not sure' when it should."
2. (0:10) Phone, Zainab: one Urdu voice answer with read-back, the blurry card with a retake hint, then the result "a person will check".
3. (0:25) Officer: the handoff package; approve with a reason; payment released.
4. (0:35) Aslam: auto-approved and paid, verify code checks.
5. (0:42) Scam checker: scam, real, not sure.
6. (0:48) Auditor: replay matches, chain verifies.
7. (0:55) "Tested on 1,223 held-out synthetic cases: 1 wrong approval. Prototype; all data simulated."
