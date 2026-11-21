# Rahat: The Last Mile, AI on Public Rails

> **Prototype. Not an official service. All identity, payment and data services are simulated.**
> Built for the Coder's Cup '26 AI Hackathon (ACM FAST-NUCES Karachi), 20 to 22 November 2026. Every person, case, message and document in this repository is invented.

**We help a low-literacy widow, a scam-targeted shopkeeper, and a community helper serving 40 families apply for and track a mock Relief Payment even though they cannot read the forms, have weak signal, get fake "relief payment" messages, and have messy or duplicated records.**

Rahat is one multi-tenant platform, not a chatbot. It decides, explains, protects, and says "I am not sure" and hands the case to a person.

This README is a working draft. It is completed in the last phase with the live URL, the eval numbers and the demo video.

## Run it

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 24. No database setup: an embedded PostgreSQL starts by itself.

```
npm install
npm run install:all     # backend and frontend dependencies
npm run migrate         # create the schema, Row Level Security and the runtime role
npm run seed            # two departments and the demo accounts
npm run dev             # API on :8000, web app on :5173
```

Open http://localhost:5173/demo for the demo sign-ins, or http://localhost:8000/docs for the API.

| Command | What it does |
|---|---|
| `npm run verify` | lint, type checks, all tests, frontend build, bundle budget, mock-data lint |
| `npm run verify:fast` | the same without database tests and without the build |
| `npm run gen:api` | export OpenAPI and regenerate the typed frontend client |
| `npm run seed -- --reset` | wipe and reseed the demo data |
| `npm run db:stop` | stop the embedded database |

## How it is built

```
Browser PWA (Preact)  --HTTPS-->  FastAPI
  offline draft + outbox            /v1 API, /docs, static web app
                                    AI modules (scikit-learn, OpenCV, Tesseract, Whisper)
                                    adapters --> mock identity, registry, payment, SMS (internal only)
                                    PostgreSQL: Row Level Security, pgvector, hash-chained audit
```

- **Access is enforced on the server, twice.** Every endpoint declares who may call it, and Postgres Row Level Security scopes every query to the caller's department. Tables with personal data also require an active consent, so withdrawing consent stops access inside the database.
- **Every action is on a hash-chained audit log.** Editing or deleting a row, even as database owner, is detected.
- **Decisions come from a cost matrix.** A wrong approval is priced far above a human review, and the thresholds are derived from those prices.
- **No silent guessing.** Every AI component returns a typed decision and can abstain.

More: [PLAN.md](PLAN.md), [docs/DECISIONS.md](docs/DECISIONS.md), [docs/CONTRACTS.md](docs/CONTRACTS.md), [docs/STATUS.md](docs/STATUS.md), [deploy/README.md](deploy/README.md).

## Real and simulated

| Real, working code | Simulated |
|---|---|
| Sign-in, roles, Row Level Security, consent enforcement, hash-chained audit | Identity registry (stands in for a national ID authority) |
| Rule engine, cost-based decisions, calibration, replay | Payment rail (stands in for an instant-payment system) |
| OCR, QR signature checks and forgery signals, on our own specimen cards | SMS, WhatsApp and email delivery (visible outbox) |
| Scam classifier and name matching, trained and tested on synthetic data | USSD gateway (simulator) |
| Urdu speech input, offline sync, webhooks, rate limits | Every person, case, message and document; billing |

Rows describe the finished system. [docs/STATUS.md](docs/STATUS.md) says what is built today.

## Limitations

- Models are trained on synthetic data. Accuracy on real data is unknown.
- Row Level Security protects against application bugs, not against someone who fully controls the API process.
- Citizens sign in with a mock phone number and a PIN. A real service would add a one-time code or device binding.
- The mock ID is `00000-NNNNNNN-C` and the mock phone is `0999-NNNNNNN`. The API refuses any other shape so that real data cannot be stored.

## Third-party software

See [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).
