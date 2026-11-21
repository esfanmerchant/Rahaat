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
    gender: str
    dob: str  # ISO date
    id_serial: int  # the mock ID is make_mock_id(id_serial)


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
    {"label": "Second admin (approves rule changes)", "kind": "staff", "role": "admin", "tenants": ["sindh-relief"],
     "identifier": "approver@sindh.rahat.example", "name": "Bilal Ahmed", "lang": "en"},
    {"label": "Officer", "kind": "staff", "role": "officer", "tenants": ["sindh-relief"],
     "identifier": "officer@sindh.rahat.example", "name": "Farhan Qureshi", "lang": "en"},
    {"label": "Second officer (approves large payments)", "kind": "staff", "role": "officer", "tenants": ["sindh-relief"],
     "identifier": "officer2@sindh.rahat.example", "name": "Sana Mirza", "lang": "en"},
    {"label": "Auditor (both departments)", "kind": "staff", "role": "auditor", "tenants": ["sindh-relief", "punjab-relief"],
     "identifier": "auditor@rahat.example", "name": "Nadia Hussain", "lang": "en"},
    {"label": "Community helper", "kind": "citizen", "role": "helper", "tenants": ["sindh-relief"],
     "identifier": "0999-0000101", "name": "Rubina Shaikh", "name_ur": "روبینہ شیخ", "lang": "ur", "district": "Karachi East"},
    {"label": "Citizen: widow", "kind": "citizen", "role": "citizen", "tenants": ["sindh-relief"],
     "identifier": "0999-0000201", "name": "Zainab Bibi", "name_ur": "زینب بی بی", "lang": "ur", "district": "Karachi East",
     "gender": "female", "dob": "1978-03-14", "id_serial": 1000201},
    {"label": "Citizen: shopkeeper", "kind": "citizen", "role": "citizen", "tenants": ["sindh-relief"],
     "identifier": "0999-0000202", "name": "Aslam Khan", "name_ur": "اسلم خان", "lang": "ur", "district": "Hyderabad",
     "gender": "male", "dob": "1981-09-02", "id_serial": 1000202},
    {"label": "Admin (Punjab)", "kind": "staff", "role": "admin", "tenants": ["punjab-relief"],
     "identifier": "admin@punjab.rahat.example", "name": "Imran Chaudhry", "lang": "en"},
    {"label": "Officer (Punjab)", "kind": "staff", "role": "officer", "tenants": ["punjab-relief"],
     "identifier": "officer@punjab.rahat.example", "name": "Hira Malik", "lang": "en"},
    {"label": "Citizen (Punjab)", "kind": "citizen", "role": "citizen", "tenants": ["punjab-relief"],
     "identifier": "0999-0000301", "name": "Rukhsana Parveen", "name_ur": "رخسانہ پروین", "lang": "ur", "district": "Lahore",
     "gender": "female", "dob": "1985-06-21", "id_serial": 1000301},
]  # fmt: skip


def secret_for(account: DemoAccount) -> str:
    return DEMO_PASSWORD if account["kind"] == "staff" else DEMO_PIN


def demo_citizens() -> list[dict[str, str]]:
    """The demo citizens with their mock IDs. Specimen cards and the mock registry are built from this."""
    from app.core.mockdata import make_mock_id

    return [
        {
            "name": a["name"], "name_ur": a.get("name_ur", ""), "phone": a["identifier"], "tenant_slug": a["tenants"][0],
            "national_id": make_mock_id(a["id_serial"]), "dob": a["dob"], "gender": a["gender"], "district": a.get("district", ""),
        }  # fmt: skip
        for a in DEMO_ACCOUNTS
        if a["role"] == "citizen"
    ]
