"""Scam checker: a local, calibrated classifier plus string-only URL, sender and money signals.

Nothing here fetches a URL or contacts a sender. Every answer is a `TypedDecision[ScamLabel]` and can abstain.
"""
