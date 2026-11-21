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

const GREEN = [0x0d, 0x5c, 0x3d];
const WHITE = [0xff, 0xff, 0xff];

// The mark, in a 512 unit box (same geometry as src/shared/components/RahatMark.tsx).
const ROOF = [
  [120, 250],
  [256, 130],
  [392, 250],
];
const ROOF_HALF_WIDTH = 22;
const HEAD = { x: 256, y: 262, r: 44 };
const BODY = { cx: 256, cy: 392, rx: 100, ry: 76 };

function distToSegment(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax;
  const dy = by - ay;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function inMark(x, y) {
  if (distToSegment(x, y, ROOF[0], ROOF[1]) <= ROOF_HALF_WIDTH) return true;
  if (distToSegment(x, y, ROOF[1], ROOF[2]) <= ROOF_HALF_WIDTH) return true;
  if (Math.hypot(x - HEAD.x, y - HEAD.y) <= HEAD.r) return true;
  const ex = (x - BODY.cx) / BODY.rx;
  const ey = (y - BODY.cy) / BODY.ry;
  return y <= BODY.cy && ex * ex + ey * ey <= 1;
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
      let mark = 0;
      for (let sy = 0; sy < S; sy += 1) {
        for (let sx = 0; sx < S; sx += 1) {
          const x = px + (sx + 0.5) / S;
          const y = py + (sy + 0.5) / S;
          if (!maskable && !inRoundedSquare(x, y, size, radius)) continue;
          bg += 1;
          // map pixel to the 512 mark box, scaled about the centre
          const u = ((x / size - 0.5) / markScale + 0.5) * 512;
          const v = ((y / size - 0.5) / markScale + 0.5) * 512;
          if (inMark(u, v)) mark += 1;
        }
      }
      const i = (py * size + px) * 4;
      const coverage = bg / (S * S);
      const m = bg === 0 ? 0 : mark / bg;
      for (let c = 0; c < 3; c += 1) rgba[i + c] = Math.round(GREEN[c] * (1 - m) + WHITE[c] * m);
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

const FAVICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0d5c3d"/>
  <path d="M120 250L256 130l136 120" fill="none" stroke="#ffffff" stroke-width="44" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="256" cy="262" r="44" fill="#ffffff"/>
  <path d="M156 392a100 76 0 0 1 200 0z" fill="#ffffff"/>
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
