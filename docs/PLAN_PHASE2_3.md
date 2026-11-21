# Phase 2 and Phase 3: the organised plan (Sat 21 Nov, 21:30 PKT)

The owner asked for Phase 2 and Phase 3 to be organised and implemented properly after the UI upgrade.
`PLAN.md` sections 2, 4 and 8 stay the source of truth; this file orders the remaining work.

## Where we are

- **Phase 0 and Phase 1 are done.** Gates 0 and 1 passed; the anchor flow runs on https://rahat-zeta.vercel.app.
- **Phase 2 (T1, the eight challenges) is built** (C01 to C08, Challenge Lab, API keys, rate limits, Helper Mode)
  but **Gate 2 has not been checked on the live URL**.
- **Phase 3 (T2) is partly built:** RAG with citations, red-team suite, Digital Twin, Scam Map, evaluation
  dashboard, mistakes ledger, offline sync, Helper Mode, verify code, symbol tracking code.
  **Missing:** feature-phone channel (USSD and SMS), agent with an approval gate, webhooks, plans and usage
  limits, appeals and complaints, anomaly detection, impact report. Memory and override learning are cut.

## Rules for this round

- Every work package (WP) is finished end to end (backend, API, tests, UI, checked on the live URL) or hidden
  behind a flag. Never a half-built screen.
- Backend packages run now, in parallel with the UI v3 agents, because they touch no frontend files.
  Their screens follow in Wave 2, after UI v3 is merged, so no two agents edit the same files.
- Feature freeze Sun 10:00, code freeze Sun 14:00, submit Sun 16:30. Anything not green by 10:00 is hidden.

## Wave 1 (now): backend work packages

| WP | What | Rubric lines | Owner |
|---|---|---|---|
| WP-A | Webhooks (HMAC-signed, retried by the job queue, delivery log, mock receiver); plans and usage limits (metered, enforced with a problem response); appeals and complaints (a different officer decides, four-eyes) | Core SaaS 8, risk and reliability 3, explainability 3 | backend-core agent |
| WP-B | Agent with an approval gate: tools, a local planner (optional Gemini planner behind the same interface), the guardrails action guard, every action waits for an officer, "the agent pays after approval" | Functional AI 12, AI workflow 8, AI quality 6 | ai-engineer agent |
| WP-C | Feature-phone channel: a USSD state machine (status by tracking code, check a message by verify code, stop sharing my data, ask for a person) and SMS commands, plus the simulator screen at `/ussd` | Problem understanding 5, practical impact 3, originality 4 | full-stack agent |

## Wave 2 (after UI v3 is merged)

| WP | What | Owner |
|---|---|---|
| WP-D | Anomaly detection (spikes per district, one payout wallet for many people, reused devices) creating review flags; impact report (time saved, handoff rate, fraud stopped, cost per claim) from real data | decision-engineer agent |
| WP-E | Staff screens for WP-A, WP-B and WP-D: agent panel in case review, webhooks, plans and usage, appeals queue, anomaly flags, impact report; `/demo` and `/live` links to `/ussd` | staff-ui agent |
| WP-F | Citizen screens: appeal a decision and make a complaint, keyed text in English and Urdu with audio | citizen-ui agent |

## Gates

- **Gate 2** (after UI v3): a verifier runs all eight Challenge Lab cards and the demo script against the live
  URL and reports pass or fail with evidence; failures are fixed or hidden.
- **Gate 3** (after Wave 2): every WP above passes its own check on the live URL or is hidden.
- **Rehearsal** (Sun morning): `docs/DEMO.md` runs twice without help.
