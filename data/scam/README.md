# Scam corpus (SYNTHETIC)

**Every message in this folder is invented** for testing the Rahat prototype's scam checker. Phone numbers are
mock `0999-NNNNNNN` numbers, IP addresses come from the documentation ranges (192.0.2.x, 198.51.100.x,
203.0.113.x), and no real organisation, bank, wallet or person is named. Real-world accuracy is unknown.

| File | What |
|---|---|
| `corpus.jsonl` | One message per line: `id`, `family`, `label`, `lang` (`en`, `ur`, `roman`), `split` (`train`, `test`), `text`, `sender`, `code` (a verify code and whether our outbox issued it), `synthetic: true` |
| `manifest.json` | Seed, generator version, SHA-256 of `corpus.jsonl`, counts, and the held-out families |

Regenerate (deterministic, seed 20261121) and check:

```
cd backend
uv run python -m app.modules.scam.corpus          # writes both files
uv run python -m app.modules.scam.corpus --check  # fails if the committed file differs from a fresh run
```

## How it is written

Messages come from **template families**: one storyline each (for example "pay a processing fee to release your
relief money"), with many surface variants per family: spelling (Roman Urdu has no standard spelling), mixed
script, Urdu digits, Arabic letter forms, numbers and amounts, sender names and numbers, links, line breaks,
typos and `Fwd:` prefixes.

Six labels: `relief_scam`, `phishing_link`, `advance_fee`, `impersonation`, `legit_program_message` and
`unknown` (an ordinary message: neither a scam we know nor a Rahat message).

Hard negatives on purpose: the real Rahat messages exactly as `notifications/templates.py` renders them (most
with their verify code), bank one-time passwords that say "do not share", money sent within a family, a school
fee that really is due, shop offers with real-looking links, credit alerts, community notices and very short
chats.

## The split

Train and test are split **by family**: about 30% of the families in every (label, language) group are held out,
so every test storyline is unseen in training. The model that runs in the app is trained on the training
families only, so the evaluation numbers describe what is deployed. Parameters were chosen by cross-validation
over training families only (`app.modules.scam.tune`), never on the test families.

One honest caveat: the first test run (21 Nov) showed two bugs that were then fixed, a clause splitter that cut
"Rs 2,500" in two and a missing rule for fees demanded in the passive voice ("a fee of Rs 2,000 must be paid").
The second fix was prompted by reading test errors, so the test families are not perfectly untouched by it.
