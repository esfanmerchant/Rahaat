"""Simulated external services: identity verification, a data-exchange registry, a payment rail and an SMS gateway.

Prototype only. Nothing here talks to a real government, bank or telecom system. The services run as their
own ASGI app (`app.mocks.main:app`), each with its own API key, latency and failure injection, so the
platform's adapters (`app.modules.integrations`) can be shown to time out, retry, trip a breaker and recover.
"""
