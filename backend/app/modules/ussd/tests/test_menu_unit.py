"""The USSD state machine, the SMS parser and the texts. No database: a fake backend answers the lookups."""

from __future__ import annotations

import itertools
import re

import pytest

from app.contracts.common import TRACKING_SYMBOLS
from app.modules.ussd import menu, smscmd, texts
from app.modules.ussd.menu import Reply, StatusInfo, Ussd


class Fake:
    """Stands in for the database. Records what the menu asked it to do."""

    def __init__(self, *, status: str | None = "in_review", genuine: bool = True, stop: menu.StopOutcome = "done") -> None:
        self._status, self._genuine, self._stop = status, genuine, stop
        self.calls: list[tuple[str, str]] = []

    def status(self, digits: str) -> StatusInfo | None:
        self.calls.append(("status", digits))
        return None if self._status is None else StatusInfo(code=f"R-{digits}", status=self._status, symbols=("moon", "star", "fish"))

    def verify(self, code: str) -> bool:
        self.calls.append(("verify", code))
        return self._genuine

    def stop(self, pin: str) -> menu.StopOutcome:
        self.calls.append(("stop", "PIN"))  # the test never keeps a PIN
        return self._stop

    def callback(self) -> None:
        self.calls.append(("callback", ""))


def run(keys: list[str], backend: Fake | None = None) -> tuple[Ussd, Reply, Fake]:
    backend = backend or Fake()
    state, reply = menu.start()
    for key in keys:
        state, reply = menu.step(state, key, backend)
    return state, reply, backend


def test_first_screen_asks_for_the_language_and_is_labelled_a_prototype() -> None:
    state, reply = menu.start()
    assert reply.kind == "CON" and "prototype" in reply.text and "1 English" in reply.text and "2 Roman Urdu" in reply.text
    assert reply.wire.startswith("CON ") and state.state == "lang"


@pytest.mark.parametrize(("choice", "lang", "marker"), [("1", "en", "Check my application"), ("2", "ru", "Meri darkhwast dekhein")])
def test_language_choice_shows_the_menu_in_that_language(choice: str, lang: str, marker: str) -> None:
    state, reply, _ = run([choice])
    assert state.lang == lang and state.state == "menu" and marker in reply.text


def test_status_path_shows_status_and_symbol_names_in_three_lines_or_fewer_of_content() -> None:
    state, reply, fake = run(["1", "1", "48213"])
    assert fake.calls == [("status", "48213")]
    lines = reply.text.split("\n")
    assert reply.kind == "CON" and lines[0] == "R-48213 (moon star fish)" and "A person is checking it" in lines[1]
    assert state.state == "status_result" and len(lines) == 4  # code line, status line, then the two navigation lines


def test_status_in_roman_urdu_uses_roman_urdu_symbol_names() -> None:
    _, reply, _ = run(["2", "1", "R-48213"])
    assert reply.text.startswith("R-48213 (chand sitara machli)") and "afsar" in reply.text


def test_typing_another_code_on_a_result_screen_checks_another_without_going_back() -> None:
    _, reply, fake = run(["1", "1", "48213", "11111"])
    assert fake.calls == [("status", "48213"), ("status", "11111")] and reply.text.startswith("R-11111")


def test_unknown_code_is_not_found_and_three_wrong_tries_end_the_session() -> None:
    fake = Fake(status=None)
    state, reply, _ = run(["1", "1", "11111"], fake)
    assert reply.kind == "CON" and "Not found" in reply.text and state.bad == 1
    state, reply = menu.step(state, "22222", fake)
    assert state.bad == 2 and reply.kind == "CON"
    state, reply = menu.step(state, "33333", fake)
    assert reply.kind == "END" and "Too many" in reply.text


def test_wrong_format_never_reaches_the_backend() -> None:
    state, reply, fake = run(["1", "1", "12"])
    assert fake.calls == [] and "exactly 5 digits" in reply.text and state.state == "status_ask"
    _, reply, fake = run(["1", "1", "abcde"])
    assert fake.calls == [] and "exactly 5 digits" in reply.text


@pytest.mark.parametrize(("genuine", "marker"), [(True, "genuine Rahat message"), (False, "cannot confirm")])
def test_verify_path_says_genuine_or_not_confirmed(genuine: bool, marker: str) -> None:
    _, reply, fake = run(["1", "2", "k7p2xq"], Fake(genuine=genuine))
    assert fake.calls == [("verify", "K7P2XQ")] and marker in reply.text


def test_verify_accepts_the_code_with_spaces_and_dashes_and_rejects_short_ones() -> None:
    _, reply, fake = run(["1", "2", "k7p-2xq"])
    assert fake.calls == [("verify", "K7P2XQ")] and reply.kind == "CON"
    _, reply, fake = run(["1", "2", "K7P"])
    assert fake.calls == [] and "6 letters or digits" in reply.text


def test_stop_path_withdraws_with_the_pin_and_ends() -> None:
    state, reply, fake = run(["1", "3", "4826"])
    assert reply.kind == "END" and "stopped using your data" in reply.text and fake.calls == [("stop", "PIN")]
    assert state.state == "lang"


def test_stop_with_a_wrong_pin_retries_then_ends_and_a_locked_account_ends_at_once() -> None:
    fake = Fake(stop="bad_pin")
    state, reply, _ = run(["1", "3", "1111"], fake)
    assert reply.kind == "CON" and "not right" in reply.text
    state, reply = menu.step(state, "2222", fake)
    state, reply = menu.step(state, "3333", fake)
    assert reply.kind == "END"
    _, reply, _ = run(["1", "3", "4826"], Fake(stop="locked"))
    assert reply.kind == "END" and "try later" in reply.text


def test_stop_needs_a_four_to_six_digit_pin_and_never_sends_other_input_to_the_backend() -> None:
    for bad in ("12", "1234567", "12ab", "48 26"):
        _, reply, fake = run(["1", "3", bad])
        assert fake.calls == [] and "4 to 6 digits" in reply.text, bad


def test_callback_needs_a_confirmation_then_creates_one_request() -> None:
    state, reply, fake = run(["1", "4"])
    assert "1 Yes, call me" in reply.text and fake.calls == []
    state, reply = menu.step(state, "1", fake)
    assert reply.kind == "END" and "a person will call you" in reply.text and fake.calls == [("callback", "")]
    _, _, fake = run(["1", "4", "0"])
    assert fake.calls == [], "backing out creates nothing"


def test_zero_goes_back_one_screen_and_double_zero_goes_to_the_main_menu() -> None:
    state, _, _ = run(["1", "1", "48213"])
    assert state.state == "status_result"
    state, reply = menu.step(state, "0", Fake())
    assert state.state == "status_ask"
    state, reply = menu.step(state, "0", Fake())
    assert state.state == "menu" and "Check my application" in reply.text
    state, reply = menu.step(state, "0", Fake())
    assert state.state == "lang"
    state, _, _ = run(["2", "3"])
    state, reply = menu.step(state, "00", Fake())
    assert state.state == "menu" and "Kisi se baat karein" in reply.text, "double zero keeps the language"


def test_zero_on_the_language_screen_ends_politely() -> None:
    _, reply, _ = run(["0"])
    assert reply.kind == "END" and "Goodbye" in reply.text


@pytest.mark.parametrize("junk", ["9", "", "abc", "#", "1 1", "  ", "٣", "0" * 70])
def test_unknown_input_repeats_the_screen_with_a_short_note_and_never_raises(junk: str) -> None:
    state, reply, _ = run(["1", junk])
    assert reply.kind == "CON" and reply.text.startswith("Wrong choice.") and state.state == "menu"
    state, reply, _ = run([junk])
    assert reply.kind == "CON" and state.state == "lang"


def test_sessions_time_out_after_three_minutes() -> None:
    assert not menu.timed_out(1000.0, 1000.0 + 180)
    assert menu.timed_out(1000.0, 1000.0 + 181)
    assert menu.timeout_reply("en").kind == "END" and "*786#" in menu.timeout_reply("en").text
    assert "dial" in menu.timeout_reply("ru").text.lower()


def test_state_survives_a_round_trip_through_storage() -> None:
    state, _, _ = run(["2", "1"])
    again = Ussd.from_dict(state.to_dict())
    assert again == state
    assert Ussd.from_dict({"state": "not-a-state", "lang": "xx", "bad": -4}) == Ussd(state="lang", lang="en", bad=0)


def test_every_screen_fits_the_182_character_ussd_limit() -> None:
    worst_symbols = {lang: " ".join(sorted(texts.SYMBOL_NAMES[s][lang] for s in TRACKING_SYMBOLS)[:3]) for lang in texts.LANGS}
    longest = {lang: max(texts.STATUS_LINES.values(), key=lambda v: len(v[lang]))[lang] for lang in texts.LANGS}
    for key, by_lang in texts.SCREENS.items():
        for lang, template in by_lang.items():
            if key == "status_result":
                for line in [v[lang] for v in texts.STATUS_LINES.values()] + [longest[lang]]:
                    for symbols in {worst_symbols[lang], "ghanti darakht parinda", "drum kite bell"}:
                        rendered = texts.screen(key, lang, code="R-99999", symbols=symbols, line=line)
                        assert len(rendered) <= texts.USSD_LIMIT, (key, lang, len(rendered))
            else:
                assert len(template) <= texts.USSD_LIMIT, (key, lang, len(template))
                if key in {"lang", "menu", "callback_confirm"}:  # the "Wrong choice." note is added to these on a bad key
                    assert len(texts.screen("wrong", lang)) + 1 + len(template) <= texts.USSD_LIMIT, (key, lang)


def test_real_screens_reached_by_every_path_fit_the_limit() -> None:
    paths = [["1"], ["2"], ["1", "1"], ["1", "2"], ["1", "3"], ["1", "4"], ["1", "1", "12345"], ["1", "2", "ABC234"], ["1", "1", "x"],
             ["1", "9"], ["1", "4", "1"], ["1", "3", "4826"], ["1", "3", "12"]]  # fmt: skip
    for lang_key, path in itertools.product(("1", "2"), paths):
        keys = [lang_key, *path[1:]] if path[0] == "1" else path
        state, reply = menu.start()
        for key in keys:
            state, reply = menu.step(state, key, Fake())
            assert len(reply.text) <= texts.USSD_LIMIT, (keys, reply.text)


def test_every_text_has_both_languages_and_at_most_three_sentences_per_message() -> None:
    for table in (texts.SCREENS, texts.SMS, texts.STATUS_LINES):
        for key, by_lang in table.items():
            assert set(by_lang) == set(texts.LANGS), key
    for key, by_lang in {**texts.SMS, **{f"line:{k}": v for k, v in texts.STATUS_LINES.items()}}.items():
        for lang, text in by_lang.items():
            sentences = [s for s in re.split(r"(?<=[.?!])\s+", re.sub(r"\{[a-z_]+\}", "X", text)) if s.strip()]
            assert len(sentences) <= 3, (key, lang, sentences)


def test_sms_replies_fit_one_sms_with_their_verify_code() -> None:
    suffix = len(" Code ABCDEF")
    for key, by_lang in texts.SMS.items():
        for lang, template in by_lang.items():
            if key == "status_ok":
                for status in texts.STATUS_LINES:
                    body = texts.sms(key, lang, code="R-99999", symbols="drum kite bell", line=texts.status_line(status, lang))
                    assert len(body) + suffix <= texts.SMS_LIMIT, (key, lang, status, len(body) + suffix)
            else:
                assert len(template) + suffix <= texts.SMS_LIMIT, (key, lang, len(template) + suffix)


def test_screens_never_ask_for_a_fee_and_say_prototype_on_the_first_two_screens() -> None:
    for lang in texts.LANGS:
        assert "prototype" in texts.screen("menu", lang) and "prototype" in texts.screen("lang", lang)
        assert "fee" not in texts.screen("callback_confirm", lang).lower().replace("never asks for a fee", "")


@pytest.mark.parametrize(
    ("text", "kind", "arg", "lang"),
    [
        ("STATUS 48213", "status", "48213", "en"), ("status R-48213", "status", "48213", "en"), ("  Status   r48213 ", "status", "48213", "en"),
        ("halat 48213", "status", "48213", "ru"), ("HAAL R-48213", "status", "48213", "ru"),
        ("VERIFY k7p2xq", "verify", "K7P2XQ", "en"), ("verify K7P 2XQ", "verify", "K7P2XQ", "en"), ("tasdeeq K7P2XQ", "verify", "K7P2XQ", "ru"),
        ("janch k7p2xq", "verify", "K7P2XQ", "ru"), ("CHECK K7P2XQ", "verify", "K7P2XQ", "en"),
        ("STOP 4826", "stop", "4826", "en"), ("roko 4826", "stop", "4826", "ru"), ("ROKEIN 482611", "stop", "482611", "ru"),
        ("HELP", "help", "", "en"), ("madad", "help", "", "ru"), ("Help me please", "help", "", "en"),
    ],
)  # fmt: skip
def test_sms_commands_in_english_and_roman_urdu(text: str, kind: str, arg: str, lang: str) -> None:
    command = smscmd.parse(text)
    assert (command.kind, command.arg, command.lang) == (kind, arg, lang)


@pytest.mark.parametrize(
    ("text", "kind"),
    [("", "unknown"), ("   ", "unknown"), ("hello", "unknown"), ("send money now", "unknown"), ("STATUS", "bad_argument"),
     ("STATUS 123", "bad_argument"), ("STATUS 1234567", "bad_argument"), ("VERIFY 12", "bad_argument"), ("STOP", "bad_argument"),
     ("STOP 12", "bad_argument"), ("STOP abcd", "bad_argument"), ("STOP 4826 5555", "bad_argument"), ("x" * 5000, "unknown")],
)  # fmt: skip
def test_sms_commands_with_bad_or_missing_arguments_or_no_command(text: str, kind: str) -> None:
    assert smscmd.parse(text).kind == kind
