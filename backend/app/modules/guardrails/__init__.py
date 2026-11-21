"""Guardrails: input, output and action checks shared by voice, RAG, OCR and messages (PLAN 7.C, C11).

All text from OCR, messages, transcripts and retrieved documents is data, never instructions. These checks
find text that tries to act like an instruction, mask personal data, and stop answers that promise
eligibility or cite sources that do not exist. Every verdict is stored in the audit log by the caller.
"""
