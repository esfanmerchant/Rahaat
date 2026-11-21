"""Link, sender, money-ask and verify-code signals. DB-free."""

from __future__ import annotations

import pytest

from app.modules.notifications import templates
from app.modules.scam import signals
from app.modules.scam.signals import SCAM_SIDE_SIGNALS, analyse, analyse_sender, analyse_url, code_candidates, cues, defang, find_urls

PAYLOAD = {"tracking_code": "R-12345", "amount_pkr": 12000, "rail_ref": "MR-00AB12CD34", "proof_kind": "income_proof"}


@pytest.mark.parametrize("lang", ["en", "ur"])
@pytest.mark.parametrize("template", sorted(templates.TEMPLATES))
def test_our_own_messages_ask_for_nothing_and_match_their_template(template: str, lang: str) -> None:
    text = templates.with_code(templates.render(template, lang, PAYLOAD), "K7M2QX", lang)
    found = analyse(text, "RAHAT")
    assert not set(found.fired()) & SCAM_SIDE_SIGNALS, found.fired()
    assert found.template is not None and found.template.template == template and found.template.code == "K7M2QX"
    assert found.codes == ("K7M2QX",) and found.sender.kind == "official"


def test_a_request_and_its_object_must_share_a_clause_and_not_be_negated() -> None:
    assert cues("Send Rs 2,500 fee to 0999-1234567")["asks_fee"]
    assert cues("Pay Rs.500 processing fee now")["asks_fee"]
    assert cues("A customs fee of Rs 2,000 must be paid before delivery.")["asks_fee"]
    assert not cues("We never ask for a fee or your PIN.")["asks_fee"]
    assert cues("We never ask for a fee or your PIN.")["safety_notice"]
    assert not cues("Do not share your PIN with anyone.")["asks_pin"]
    assert cues("If you do not pay the fee today your relief will be cancelled")["asks_fee"], "a conditional threat keeps its ask"
    assert cues("Reply with your PIN and CNIC number to release the payment")["asks_pin"]


def test_urdu_and_roman_urdu_asks() -> None:
    assert cues("رقم وصول کرنے کے لیے اپنا پن کوڈ بتائیں۔")["asks_pin"]
    assert not cues("اپنا نام اور پتہ لکھیں")["asks_pin"], "'پن' inside 'اپنا' is not a PIN"
    assert not cues("پن کوڈ کسی کو نہ بتائیں")["asks_pin"]
    assert not cues("ہم آپ کو پیغام بھیجیں گے")["asks_money"], "future tense is not a request"
    roman = cues("Raqam hasil karne ke liye 500 rupay fee is number par bhejein")
    assert roman["asks_fee"] and roman["pay_to_receive"]
    assert not cues("Ammi maine aap ko 2000 bhej diye hain")["asks_money"], "past tense is not a request"
    assert cues("jo code aaya hai woh bata dein")["asks_otp"]


def test_links_are_found_refanged_and_shown_defanged() -> None:
    text = "Claim at hxxps://rahat-gov[.]pk.claim-now.xyz/verify?id=00000-1234567-1, or bit.ly/3xYz. Mail help@example.com. Rs.500 only"
    urls = find_urls(text)
    assert urls == ["https://rahat-gov.pk.claim-now.xyz/verify?id=00000-1234567-1", "bit.ly/3xYz"]
    finding = analyse_url(urls[0])
    assert finding is not None and finding.risk == "high"
    assert {"official_name_in_subdomain", "odd_tld", "phishy_words"} <= set(finding.flags)
    assert finding.defanged == "hxxps://rahat-gov[.]pk[.]claim-now[.]xyz/verify?…", "query strings are cut"
    assert defang("http://a.b/c") == "hxxp://a[.]b/c"


@pytest.mark.parametrize(
    ("url", "flag"),
    [
        ("rahat-relief.top/claim", "lookalike_official"),
        ("http://r4hat-pk.com", "lookalike_official"),
        ("https://tinyurl.com/abc123", "shortener"),
        ("http://203.0.113.7/rahat/claim", "ip_host"),
        ("https://xn--rhat-9na.com/", "punycode"),
        ("https://rаhat-relief.com/", "punycode"),
        ("http://example.com/x", "http"),
        ("https://rahat.example.xyz/app/relief.apk", "apk_download"),
        ("https://wa.me/929991234567", "messaging_link"),
    ],
)
def test_link_flags(url: str, flag: str) -> None:
    finding = analyse_url(url)
    assert finding is not None and flag in finding.flags, finding


def test_an_ordinary_https_link_is_low_risk_and_gov_pk_is_not_a_lookalike() -> None:
    shop = analyse_url("https://www.citymart.pk/offers")
    assert shop is not None and shop.risk == "low" and not shop.flags
    gov = analyse_url("https://www.rahat.gov.pk/apply")
    assert gov is not None and "lookalike_official" not in gov.flags


def test_senders() -> None:
    assert analyse_sender("RAHAT").kind == "official"
    assert analyse_sender("Rahat").kind == "official"
    assert analyse_sender("RAHAT-GOV").kind == "lookalike"
    assert analyse_sender("R4HAT").kind == "lookalike"
    assert analyse_sender("GOVT-RELIEF").kind == "lookalike"
    mobile = analyse_sender("0999-1234567")
    assert mobile.kind == "mobile" and mobile.shown == "••••••••567", "a number is stored masked"
    assert analyse_sender("+92 999 1234567").kind == "mobile"
    assert analyse_sender("SITARABANK").kind == "alpha"
    assert analyse_sender("8080").kind == "short_code"
    assert analyse_sender(None).kind == "none"
    assert analyse_sender("SINDH-RAHAT", official_sender="SINDH-RAHAT").kind == "official"


def test_a_personal_number_posing_as_official() -> None:
    found = analyse("Rahat office: your relief of Rs 12,000 is pending. Call the officer now.", "0999-7654321")
    assert found.values["sender_mobile_official"] == 1.0


def test_verify_code_candidates() -> None:
    assert code_candidates("... We never ask for a fee. Code K7M2QX") == (["K7M2QX"], False)
    assert code_candidates("  k7m-2qx ") == (["K7M2QX"], True)
    assert code_candidates("آپ کو 12,000 روپے ملیں گے۔ کوڈ AB3CDE") == (["AB3CDE"], False)
    assert signals.looks_like_our_code("K7M2QX")
    assert not signals.looks_like_our_code("482913"), "a bank OTP is digits only"
    assert not signals.looks_like_our_code("K0M1QX"), "0 and 1 are not in our alphabet"


def test_text_normalisation_removes_tricks() -> None:
    found = analyse("Send your P​IN to 0999‐1234567", None)
    assert found.cue["asks_pin"], "a zero-width space does not hide the word"
    assert analyse("راحت پروگرام", None).script == "ur"
    assert analyse("Aap ka naam list mein hai, raqam hasil karein", None).script == "roman"
    assert analyse("Your parcel is waiting at the office", None).script == "en"
