// Generates the PWA icons, the favicon and the silent MP3 used to unlock audio.
// No dependencies: a tiny rasteriser and PNG encoder on node:zlib.
//   node scripts/make-assets.mjs
// The outputs are committed; re-run only when the mark changes.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { crc32, deflateSync } from 'node:zlib';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const pub = join(root, 'public');

const NIGHT = [0x0b, 0x10, 0x26];
const GOLD = [0xff, 0xd3, 0x6e];
const EMERALD = [0x4e, 0xe6, 0xa6];

// The Noor emblem in a 512 unit box (same geometry as src/shared/components/Emblem.tsx, scaled 4.2 about the
// centre): two squares make the eight-point star, a lamp at the centre, eight homes around it.
const K = 4.2;
const STROKE_HALF = 2.25 * K;
const SQUARE_HALF = 28 * K;
const DIAMOND_HALF_DIAGONAL = 39.6 * K;
const LAMP_R = 8.5 * K;
const HOME_R = 3.4 * K;
const HOME_ORBIT = 44 * K;

/** 0 = background, 1 = gold (star and lamp), 2 = emerald (homes). */
function inMark(x, y) {
  const dx = x - 256;
  const dy = y - 256;
  if (Math.hypot(dx, dy) <= LAMP_R) return 1;
  for (let k = 0; k < 8; k += 1) {
    const angle = ((22.5 + k * 45) * Math.PI) / 180;
    if (Math.hypot(dx - HOME_ORBIT * Math.cos(angle), dy - HOME_ORBIT * Math.sin(angle)) <= HOME_R) return 2;
  }
  const square = Math.max(Math.abs(dx), Math.abs(dy)); // 0 at the centre, SQUARE_HALF on the edge
  if (Math.abs(square - SQUARE_HALF) <= STROKE_HALF) return 1;
  const diamond = Math.abs(dx) + Math.abs(dy); // DIAMOND_HALF_DIAGONAL on the edge
  if (Math.abs(diamond - DIAMOND_HALF_DIAGONAL) <= STROKE_HALF * Math.SQRT2) return 1;
  return 0;
}

function inRoundedSquare(x, y, size, radius) {
  const cx = Math.min(Math.max(x, radius), size - radius);
  const cy = Math.min(Math.max(y, radius), size - radius);
  return Math.hypot(x - cx, y - cy) <= radius;
}

/**
 * @param {number} size output pixels
 * @param {{ maskable: boolean }} options maskable: full-bleed background, mark inside the 80% safe zone
 */
function renderIcon(size, { maskable }) {
  const S = 4; // 4x4 supersampling
  const rgba = Buffer.alloc(size * size * 4);
  const markScale = maskable ? 0.72 : 1;
  const radius = maskable ? 0 : (96 / 512) * size;
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      let bg = 0;
      let gold = 0;
      let emerald = 0;
      for (let sy = 0; sy < S; sy += 1) {
        for (let sx = 0; sx < S; sx += 1) {
          const x = px + (sx + 0.5) / S;
          const y = py + (sy + 0.5) / S;
          if (!maskable && !inRoundedSquare(x, y, size, radius)) continue;
          bg += 1;
          // map pixel to the 512 mark box, scaled about the centre
          const u = ((x / size - 0.5) / markScale + 0.5) * 512;
          const v = ((y / size - 0.5) / markScale + 0.5) * 512;
          const hit = inMark(u, v);
          if (hit === 1) gold += 1;
          else if (hit === 2) emerald += 1;
        }
      }
      const i = (py * size + px) * 4;
      const coverage = bg / (S * S);
      const g = bg === 0 ? 0 : gold / bg;
      const e = bg === 0 ? 0 : emerald / bg;
      for (let c = 0; c < 3; c += 1) rgba[i + c] = Math.round(NIGHT[c] * (1 - g - e) + GOLD[c] * g + EMERALD[c] * e);
      rgba[i + 3] = Math.round(coverage * 255);
    }
  }
  return encodePng(size, size, rgba);
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body) >>> 0);
  return Buffer.concat([len, body, crc]);
}

function encodePng(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (width * 4 + 1)] = 0; // filter: none
    rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// MPEG-1 Layer III, 32 kbit/s, 44.1 kHz, mono; 104-byte frames whose side info
// and main data are all zero decode to silence. 20 frames is about half a second.
function silentMp3(frames = 20) {
  const frame = Buffer.alloc(104);
  frame.set([0xff, 0xfb, 0x10, 0xc0], 0);
  return Buffer.concat(Array.from({ length: frames }, () => frame));
}

const HOMES = Array.from({ length: 8 }, (_, k) => {
  const angle = ((22.5 + k * 45) * Math.PI) / 180;
  return `<circle cx="${(256 + HOME_ORBIT * Math.cos(angle)).toFixed(1)}" cy="${(256 + HOME_ORBIT * Math.sin(angle)).toFixed(1)}" r="${HOME_R.toFixed(1)}" fill="#4ee6a6"/>`;
}).join(' ');
const FAVICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0b1026"/>
  <g fill="none" stroke="#ffd36e" stroke-width="${(STROKE_HALF * 2).toFixed(1)}" stroke-linejoin="round">
    <rect x="${256 - SQUARE_HALF}" y="${256 - SQUARE_HALF}" width="${SQUARE_HALF * 2}" height="${SQUARE_HALF * 2}"/>
    <path d="M256 ${256 - DIAMOND_HALF_DIAGONAL}L${256 + DIAMOND_HALF_DIAGONAL} 256L256 ${256 + DIAMOND_HALF_DIAGONAL}L${256 - DIAMOND_HALF_DIAGONAL} 256z"/>
  </g>
  <circle cx="256" cy="256" r="${LAMP_R.toFixed(1)}" fill="#ffd36e"/>
  ${HOMES}
</svg>
`;

function write(relative, data) {
  const target = join(pub, relative);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, data);
  console.log(`wrote public/${relative} (${data.length} bytes)`);
}

write('favicon.svg', FAVICON);
write('icons/icon-192.png', renderIcon(192, { maskable: false }));
write('icons/icon-512.png', renderIcon(512, { maskable: false }));
write('icons/icon-maskable-512.png', renderIcon(512, { maskable: true }));
write('icons/apple-touch-icon.png', renderIcon(180, { maskable: true }));
write('audio/silence.mp3', silentMp3());
