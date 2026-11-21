"""Voice answers (PLAN 7.C, C4): a spoken answer becomes a typed form value, or the app asks again.

Speech recognition for Urdu is imperfect, so every answer is interpreted against the type the question
expects, gated on confidence, and always read back for confirmation before it is saved.
"""
