// Generates the fixed voice prompts: public/audio/{lang}/{key}.mp3, one per
// message key in the dictionary, plus public/audio/{lang}/index.json (the keys
// that have a file, with a hash of the voice and text).
//
//   node scripts/make-audio.mjs            # Urdu and English
//   node scripts/make-audio.mjs ur         # one language
//   node scripts/make-audio.mjs ur --force # regenerate everything
//
// Uses Microsoft Edge's online neural voices through `uvx edge-tts` (needs uv
// and the network). Only changed or missing prompts are regenerated, files for
// keys that no longer exist are removed. The outputs are committed, so the app
// never needs the network to speak. A team member's own recording can replace
// any file (PLAN 3, item 9): keep the name, and the next run leaves it alone
// unless the text changes.
//
// Node 22.6+ (type stripping) reads the TypeScript dictionaries directly.
//
// The server's own fixed sentences (scam answers, decision explanations) are
// recorded too, from scripts/server-prompts.json (node scripts/server-prompts.mjs),
// under the server's audio keys: public/audio/{lang}/scam.reason.asks_fee.mp3.
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const i18n = join(root, 'src', 'shared', 'i18n');

const VOICES = {
  ur: 'ur-PK-UzmaNeural',
  en: 'en-IN-NeerjaNeural', // the closest South Asian English voice available
};

// What the voice should say where the screen shows digits (a voice may read
// "15,000" or "0999" oddly). The screen text stays as it is.
const SPOKEN = {
  ur: {
    income_under_15k: 'پندرہ ہزار روپے سے کم',
    income_15k_30k: 'پندرہ ہزار سے تیس ہزار روپے',
    income_30k_50k: 'تیس ہزار سے پچاس ہزار روپے',
    income_over_50k: 'پچاس ہزار روپے سے زیادہ',
    login_phone_invalid: 'صفر نو نو نو کے بعد ساتوں ہندسے لکھیں۔',
  },
  en: {
    login_phone_invalid: 'Type all seven numbers after zero nine nine nine.',
    income_under_15k: 'Less than fifteen thousand rupees',
    income_15k_30k: 'Fifteen thousand to thirty thousand rupees',
    income_30k_50k: 'Thirty thousand to fifty thousand rupees',
    income_over_50k: 'More than fifty thousand rupees',
  },
};

// Not spoken: names of things shown next to their own spoken prompt.
const SKIP = new Set(['lang_name', 'app_name']);

const args = process.argv.slice(2);
const force = args.includes('--force');
const langs = args.filter((arg) => !arg.startsWith('--'));
const targets = langs.length > 0 ? langs : Object.keys(VOICES);
const CONCURRENCY = Number(process.env.AUDIO_CONCURRENCY) || 4;
// --adopt: a file that exists for a key the index does not know yet is kept (an earlier run was stopped before it wrote the index).
const adopt = args.includes('--adopt');

async function dictionary(code) {
  const module = await import(pathToFileURL(join(i18n, `${code}.ts`)).href);
  const dict = module[code];
  if (!dict) throw new Error(`src/shared/i18n/${code}.ts has no export named ${code}`);
  // The strings of the lazy chunks (more.{lang}.ts) are recorded too.
  const more = await import(pathToFileURL(join(i18n, `more.${code}.ts`)).href);
  return { ...dict, ...(more[`${code}More`] ?? {}) };
}

function speakable(dict, code) {
  const out = {};
  for (const [key, value] of Object.entries(dict)) {
    if (SKIP.has(key) || typeof value !== 'string') continue;
    if (value.includes('{')) continue; // has a {param}: cannot be recorded in advance
    out[key] = (SPOKEN[code]?.[key] ?? value).replace(/[⁦-⁩]/g, '').trim();
  }
  return out;
}

/** The server's sentences for this language, keyed by the audio key the API names. */
function serverTexts(code) {
  const file = join(root, 'scripts', 'server-prompts.json');
  if (!existsSync(file)) return {};
  const out = {};
  for (const [key, texts] of Object.entries(JSON.parse(readFileSync(file, 'utf8')))) {
    const text = texts?.[code];
    if (typeof text === 'string' && text.trim() && /^[\w.-]+$/.test(key)) out[key] = text.replace(/[⁦-⁩]/g, '').trim();
  }
  return out;
}

function hash(voice, text) {
  return createHash('sha1').update(`${voice}\n${text}`).digest('hex').slice(0, 16);
}

function edgeTts(voice, text, file) {
  return new Promise((resolve, reject) => {
    execFile(
      'uvx',
      ['edge-tts', '--voice', voice, '--text', text, '--write-media', file],
      { timeout: 120_000, windowsHide: true },
      (error, _stdout, stderr) => {
        if (error) reject(new Error(`${error.message}\n${stderr}`));
        else resolve();
      },
    );
  });
}

async function run(code) {
  const voice = VOICES[code];
  if (!voice) throw new Error(`no voice for language "${code}"`);
  const dir = join(root, 'public', 'audio', code);
  mkdirSync(dir, { recursive: true });
  const indexPath = join(dir, 'index.json');
  const previous = existsSync(indexPath) ? JSON.parse(readFileSync(indexPath, 'utf8')).files ?? {} : {};
  const texts = { ...speakable(await dictionary(code), code), ...serverTexts(code) };

  const todo = [];
  const files = {};
  for (const [key, text] of Object.entries(texts)) {
    const digest = hash(voice, text);
    const file = join(dir, `${key}.mp3`);
    if (!force && (previous[key] === digest || (adopt && previous[key] === undefined)) && existsSync(file) && statSync(file).size > 0) {
      files[key] = digest;
    } else {
      todo.push({ key, text, digest, file });
    }
  }

  let done = 0;
  const failed = [];
  const worker = async () => {
    for (;;) {
      const job = todo.shift();
      if (!job) return;
      try {
        await edgeTts(voice, job.text, job.file);
        if (!existsSync(job.file) || statSync(job.file).size === 0) throw new Error('empty file');
        files[job.key] = job.digest;
        done += 1;
        if (done % 20 === 0) console.log(`  ${code}: ${done} generated`);
      } catch (error) {
        failed.push(job.key);
        console.error(`  ${code}/${job.key}: ${String(error.message).split('\n')[0]}`);
      }
    }
  };
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));

  // Remove recordings for keys that no longer exist.
  for (const name of readdirSync(dir)) {
    if (!name.endsWith('.mp3')) continue;
    const key = name.slice(0, -4);
    if (!(key in texts)) {
      unlinkSync(join(dir, name));
      console.log(`  ${code}: removed ${name}`);
    }
  }

  const sorted = Object.fromEntries(Object.keys(files).sort().map((key) => [key, files[key]]));
  writeFileSync(indexPath, `${JSON.stringify({ voice, files: sorted }, null, 2)}\n`);
  console.log(`${code}: ${Object.keys(sorted).length} prompts (${done} new), ${failed.length} failed -> public/audio/${code}/`);
  return failed.length;
}

let failures = 0;
for (const code of targets) failures += await run(code);
if (failures > 0) {
  console.error(`${failures} prompts could not be generated (network or uv missing?). The app falls back to a device voice for those.`);
  process.exit(1);
}
