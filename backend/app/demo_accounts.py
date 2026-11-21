"""Demo tenants and accounts. Every name, email and number here is invented.

The seed creates them, and GET /v1/demo/accounts lists them outside prod so judges can sign in.
"""

from __future__ import annotations

from typing import TypedDict

DEMO_PASSWORD = "Rahat-Demo-2026!"
DEMO_PIN = "4826"


class DemoTenant(TypedDict):
    slug: str
    name: str
    name_ur: str
    region: str


class DemoAccount(TypedDict, total=False):
    label: str
    kind: str  # staff | citizen
    role: str
    tenants: list[str]  # the first one is where the account signs in by default
    identifier: str  # email for staff, mock phone for citizens and helpers
    name: str
    name_ur: str
    lang: str
    district: str


DEMO_TENANTS: list[DemoTenant] = [
    {
        "slug": "sindh-relief",
        "name": "Sindh Social Protection Department (mock)",
        "name_ur": "محکمہ سماجی تحفظ سندھ (فرضی)",
        "region": "PK-SD",
    },
    {
        "slug": "punjab-relief",
        "name": "Punjab Relief Department (mock)",
        "name_ur": "محکمہ ریلیف پنجاب (فرضی)",
        "region": "PK-PB",
    },
]

DEMO_ACCOUNTS: list[DemoAccount] = [
    {"label": "Admin", "kind": "staff", "role": "admin", "tenants": ["sindh-relief"],
     "identifier": "admin@sindh.rahat.example", "name": "Ayesha Siddiqui", "lang": "en"},
    {"label": "Second approver (admin)", "kind": "staff", "role": "admin", "tenants": ["sindh-relief"],
     "identifier": "approver@sindh.rahat.example", "name": "Bilal Ahmed", "lang": "en"},
    {"label": "Officer", "kind": "staff", "role": "officer", "tenants": ["sindh-relief"],
     "identifier": "officer@sindh.rahat.example", "name": "Farhan Qureshi", "lang": "en"},
    {"label": "Second officer", "kind": "staff", "role": "officer", "tenants": ["sindh-relief"],
     "identifier": "officer2@sindh.rahat.example", "name": "Sana Mirza", "lang": "en"},
    {"label": "Auditor (both departments)", "kind": "staff", "role": "auditor", "tenants": ["sindh-relief", "punjab-relief"],
     "identifier": "auditor@rahat.example", "name": "Nadia Hussain", "lang": "en"},
    {"label": "Community helper", "kind": "citizen", "role": "helper", "tenants": ["sindh-relief"],
     "identifier": "0999-0000101", "name": "Rubina Shaikh", "name_ur": "روبینہ شیخ", "lang": "ur", "district": "Karachi East"},
    {"label": "Citizen: widow", "kind": "citizen", "role": "citizen", "tenants": ["sindh-relief"],
     "identifier": "0999-0000201", "name": "Zainab Bibi", "name_ur": "زینب بی بی", "lang": "ur", "district": "Karachi East"},
    {"label": "Citizen: shopkeeper", "kind": "citizen", "role": "citizen", "tenants": ["sindh-relief"],
     "identifier": "0999-0000202", "name": "Aslam Khan", "name_ur": "اسلم خان", "lang": "ur", "district": "Hyderabad"},
    {"label": "Admin (Punjab)", "kind": "staff", "role": "admin", "tenants": ["punjab-relief"],
     "identifier": "admin@punjab.rahat.example", "name": "Imran Chaudhry", "lang": "en"},
    {"label": "Officer (Punjab)", "kind": "staff", "role": "officer", "tenants": ["punjab-relief"],
     "identifier": "officer@punjab.rahat.example", "name": "Hira Malik", "lang": "en"},
    {"label": "Citizen (Punjab)", "kind": "citizen", "role": "citizen", "tenants": ["punjab-relief"],
     "identifier": "0999-0000301", "name": "Rukhsana Parveen", "name_ur": "رخسانہ پروین", "lang": "ur", "district": "Lahore"},
]  # fmt: skip


def secret_for(account: DemoAccount) -> str:
    return DEMO_PASSWORD if account["kind"] == "staff" else DEMO_PIN
