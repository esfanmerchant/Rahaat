// Snapshot of the fixed sentences the server speaks through `audio_keys`
// (scam checker answers, decision explanations), so make-audio.mjs can record
// them under the same names: public/audio/{lang}/scam.reason.asks_fee.mp3.
//
//   node scripts/server-prompts.mjs     # needs uv and the backend (no database)
//
// Writes scripts/server-prompts.json: { "<audio key>": { "en": "...", "ur": "..." } }.
// Commit it with the audio; re-run when the backend's wording changes.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const backend = join(root, '..', 'backend');

const PYTHON = `
import json, sys
from app.modules.scam.explain import audio_manifest
from app.modules.decision.explain import CITIZEN_TEMPLATES, NEXT_STEPS
from app.modules.voice.phrases import VOICE_KEYS
from app.modules.rag.answer import MESSAGES
out = dict(audio_manifest())
# Voice read-backs and the rules assistant's fixed sentences (backend VOICE_KEYS, MESSAGES).
for key, texts in {**VOICE_KEYS, **MESSAGES}.items():
    out[key] = dict(texts)
for code, (_pictogram, _next, texts) in CITIZEN_TEMPLATES.items():
    out[f"reason.{code}"] = {lang: " ".join(sentences) for lang, sentences in texts.items()}
for code, texts in NEXT_STEPS.items():
    out[f"next.{code}"] = dict(texts)
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
`;

const raw = execFileSync('uv', ['run', '--directory', backend, 'python', '-c', PYTHON], {
  encoding: 'utf8',
  maxBuffer: 8 * 1024 * 1024,
  windowsHide: true,
});
const prompts = JSON.parse(raw);
for (const [key, texts] of Object.entries(prompts)) {
  if (!/^[\w.-]+$/.test(key)) throw new Error(`audio key "${key}" is not a safe file name`);
  if (typeof texts.en !== 'string' || typeof texts.ur !== 'string') throw new Error(`"${key}" needs English and Urdu`);
}
writeFileSync(join(root, 'scripts', 'server-prompts.json'), `${JSON.stringify(prompts, null, 1)}\n`);
console.log(`server-prompts.json: ${Object.keys(prompts).length} prompts`);
