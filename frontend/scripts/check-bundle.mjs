// Citizen JS budget (CLAUDE.md): at most 100 KB gzipped for the citizen routes; aim for 60.
//
// Reads dist/.vite/manifest.json and walks from the entry:
//   - initial: the entry and everything it imports statically (loads on first paint);
//   - lazy citizen: dynamic imports reachable from there (for example workbox-window,
//     or a lazy citizen screen), which can also load on citizen routes.
// Staff and demo chunks (src/staff/**) are excluded: citizens never load them.
// Both initial and lazy citizen JS count against the budget, so the number is honest.
//
// Exit 1 when over budget, when staff code is statically reachable from the
// entry, or when the build is missing.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const BUDGET_BYTES = 100 * 1000;
const TARGET_BYTES = 60 * 1000;

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const manifestPath = join(dist, '.vite', 'manifest.json');

if (!existsSync(manifestPath)) {
  console.error(`check:bundle: ${manifestPath} not found. Run "npm run build" first.`);
  process.exit(1);
}

/** @type {Record<string, {file: string, src?: string, name?: string, isEntry?: boolean, isDynamicEntry?: boolean, imports?: string[], dynamicImports?: string[]}>} */
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));

const isExcluded = (key) => {
  const chunk = manifest[key];
  if (!chunk) return false;
  return (
    /(^|\/)src\/staff\//.test(chunk.src ?? key) ||
    /^assets\/(staff|demo)-/.test(chunk.file) ||
    chunk.name === 'staff' ||
    chunk.name === 'demo'
  );
};

const entries = Object.keys(manifest).filter((key) => manifest[key].isEntry);
if (entries.length === 0) {
  console.error('check:bundle: no entry chunk in the manifest.');
  process.exit(1);
}

function staticClosure(starts) {
  const seen = new Set();
  const stack = [...starts];
  while (stack.length > 0) {
    const key = stack.pop();
    if (seen.has(key) || !manifest[key]) continue;
    seen.add(key);
    for (const next of manifest[key].imports ?? []) stack.push(next);
  }
  return seen;
}

const initial = staticClosure(entries);
const leaked = [...initial].filter(isExcluded);

const citizen = new Set(initial);
const lazyCitizen = new Set();
const excluded = new Set();
let frontier = [...initial];
while (frontier.length > 0) {
  const next = [];
  for (const key of frontier) {
    for (const dyn of manifest[key]?.dynamicImports ?? []) {
      if (isExcluded(dyn)) {
        for (const k of staticClosure([dyn])) if (!citizen.has(k)) excluded.add(k);
        continue;
      }
      for (const k of staticClosure([dyn])) {
        if (citizen.has(k)) continue;
        citizen.add(k);
        lazyCitizen.add(k);
        next.push(k);
      }
    }
  }
  frontier = next;
}
for (const key of citizen) excluded.delete(key);

const sizeOf = (file) => {
  const buffer = readFileSync(join(dist, file));
  return { raw: buffer.length, gzip: gzipSync(buffer, { level: 9 }).length };
};

const rows = [];
const add = (keys, group) => {
  for (const key of keys) {
    const file = manifest[key].file;
    if (!file.endsWith('.js')) continue;
    rows.push({ group, file, ...sizeOf(file) });
  }
};
add(initial, 'initial');
add(lazyCitizen, 'lazy citizen');
add(excluded, 'excluded (staff/demo)');

const kb = (bytes) => `${(bytes / 1000).toFixed(1)} KB`;
const pad = (value, width) => String(value).padEnd(width);
const padStart = (value, width) => String(value).padStart(width);
const fileWidth = Math.max(4, ...rows.map((r) => r.file.length));

console.log(`\n${pad('group', 22)} ${pad('file', fileWidth)} ${padStart('raw', 10)} ${padStart('gzip', 10)}`);
console.log('-'.repeat(22 + fileWidth + 24));
for (const row of rows) {
  console.log(`${pad(row.group, 22)} ${pad(row.file, fileWidth)} ${padStart(kb(row.raw), 10)} ${padStart(kb(row.gzip), 10)}`);
}

const sum = (group) => rows.filter((r) => r.group === group).reduce((total, r) => total + r.gzip, 0);
const initialGzip = sum('initial');
const lazyGzip = sum('lazy citizen');
const citizenGzip = initialGzip + lazyGzip;
const staffGzip = sum('excluded (staff/demo)');

console.log('-'.repeat(22 + fileWidth + 24));
console.log(`citizen initial JS (gzip):      ${kb(initialGzip)}`);
console.log(`citizen lazy JS (gzip):         ${kb(lazyGzip)}`);
console.log(`CITIZEN TOTAL JS (gzip):        ${kb(citizenGzip)}   budget ${kb(BUDGET_BYTES)}, target ${kb(TARGET_BYTES)}`);
console.log(`staff + demo JS (gzip, excluded): ${kb(staffGzip)}`);
console.log('(the service worker script is not page JS and is not counted)\n');

let failed = false;
if (leaked.length > 0) {
  console.error(`FAIL: staff/demo code is statically imported by the citizen entry: ${leaked.map((k) => manifest[k].file).join(', ')}`);
  failed = true;
}
if (citizenGzip > BUDGET_BYTES) {
  console.error(`FAIL: citizen JS ${kb(citizenGzip)} is over the ${kb(BUDGET_BYTES)} budget.`);
  failed = true;
} else if (citizenGzip > TARGET_BYTES) {
  console.warn(`WARN: citizen JS ${kb(citizenGzip)} is over the ${kb(TARGET_BYTES)} target (budget still met).`);
}
if (failed) process.exit(1);
console.log(`PASS: citizen JS ${kb(citizenGzip)} <= ${kb(BUDGET_BYTES)}.`);
