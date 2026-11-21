# Rahat policy corpus (synthetic)

Prototype. Not an official service. All identity, payment and data services are simulated.

These documents are invented for the Rahat prototype. They describe the mock Relief Payment exactly as rule
version 1 decides it (`backend/app/seed.py`, `RULES_V1`): identity confirmed by the signed card or the
registry, monthly household income at or below Rs 30,000, not already receiving the payment, and priority
for widows, people with a disability and households of five or more. The payment is Rs 12,000, once.

The rules assistant (`POST /v1/ask`) answers only with sentences copied from these files, each with a
citation to the document, its version and the section.

## Format

One file per document and language: `<doc>.<lang>.md`. A front matter block names the document:

```
---
doc: rahat-rules        stable id, the same in every language
lang: en                en or ur
version: 1              bump it whenever the text changes; a changed text with the same version is refused
title: Rahat Relief Payment Rules
rule_version: 1         the rule version this text describes
status: approved        only approved documents are searched
---
```

Each `## Heading {#section-id}` starts a section; the section id is the same in English and Urdu. A section
holds short sentences, one idea each, written in the third person: an answer is a copied sentence, so a
sentence such as "you will get the money" would read as a promise, and the output guard blocks it.

## Changing a document

Edit the text, bump `version`, and restart the app (or call `POST /v1/kb/ingest` as an admin). The old
version is kept and marked `retired`; answers given earlier still cite the version they used.
