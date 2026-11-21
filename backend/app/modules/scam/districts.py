"""Districts the Scam Map knows. Location is kept at district level only; free text is never stored.

A district that is not on the list is dropped (stored as unknown), so an address typed into the field
cannot end up in the database.
"""

from __future__ import annotations

import re

SINDH = (
    "Karachi Central", "Karachi East", "Karachi South", "Karachi West", "Korangi", "Malir", "Keamari", "Hyderabad", "Jamshoro",
    "Matiari", "Tando Allahyar", "Tando Muhammad Khan", "Badin", "Thatta", "Sujawal", "Mirpurkhas", "Umerkot", "Tharparkar", "Sanghar",
    "Shaheed Benazirabad", "Naushahro Feroze", "Khairpur", "Sukkur", "Ghotki", "Larkana", "Qambar Shahdadkot", "Shikarpur",
    "Jacobabad", "Kashmore", "Dadu",
)  # fmt: skip
PUNJAB = (
    "Lahore", "Faisalabad", "Rawalpindi", "Gujranwala", "Multan", "Bahawalpur", "Sargodha", "Sialkot", "Sheikhupura", "Rahim Yar Khan",
    "Jhang", "Dera Ghazi Khan", "Gujrat", "Sahiwal", "Kasur", "Okara", "Muzaffargarh", "Khanewal", "Vehari", "Bahawalnagar", "Attock",
    "Jhelum", "Chakwal", "Mianwali", "Bhakkar", "Layyah", "Rajanpur", "Lodhran", "Pakpattan", "Toba Tek Singh", "Hafizabad",
    "Mandi Bahauddin", "Narowal", "Nankana Sahib", "Chiniot", "Khushab",
)  # fmt: skip
BY_REGION = {"PK-SD": SINDH, "PK-PB": PUNJAB}
_INDEX = {re.sub(r"[^a-z]", "", name.lower()): name for name in (*SINDH, *PUNJAB)}


def normalise_district(value: str | None) -> str | None:
    """The canonical district name, or None when it is not a district we know."""
    if not value:
        return None
    return _INDEX.get(re.sub(r"[^a-z]", "", value.lower()))
