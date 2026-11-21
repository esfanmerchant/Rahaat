"""The officer's agent: it reads a case, proposes one action, and an officer approves it before anything happens (PLAN 7.C, C10).

Read tools run at once. Action tools never do: each waits for a signed-in officer, and the action guard checks it
again at that moment. The local planner is deterministic and needs no network; Gemini is optional behind the same interface.
All case text (OCR, notes, messages) is data: no planner reads it as an instruction.
"""
