/**
 * The Loom of Light: a WebGL scene of the real decision engine (three.js, loaded only when this module is imported).
 *
 * Every particle is one synthetic labelled case from GET /v1/public/pulse. It rises from a dark horizon, flows into the
 * eight-point-star gate (the cost-matrix decision) and then takes the path its real `route` and `p_ok` dictate:
 * emerald to a lattice of homes, a saffron loop back for proof, indigo to a human desk, a thin madder line for a hard-rule
 * rejection. Scam reports are madder sparks that strike a shield and scatter. Nothing is simulated beyond the motion.
 *
 * Positions are computed on the CPU each frame (6,000 cubic Beziers cost well under a millisecond), which also gives
 * exact hover picking and exact arrival counts (a home lights when an approved particle lands).
 */
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  DynamicDrawUsage,
  Group,
  LineSegments,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Scene,
  ShaderMaterial,
  Vector3,
  WebGLRenderer,
} from 'three';
import { laneOf, type Lane, type ReplayCase } from './types';

export interface HoverInfo {
  c: ReplayCase;
  lane: Lane;
  x: number;
  y: number;
}

export interface LabelPoint {
  id: string;
  x: number;
  y: number;
  visible: boolean;
}

export interface SceneHooks {
  onHover: (info: HoverInfo | null) => void;
  onLabels: (labels: LabelPoint[]) => void;
  onFail: (why: string) => void;
}

export interface SceneHandle {
  setCases: (cases: readonly ReplayCase[]) => void;
  setScamCount: (n: number) => void;
  dispose: () => void;
}

export const MAX_PARTICLES = 6000;
const MAX_SPARKS = 220;
const FOV = 46;

// World layout. Cases flow along +x: horizon at the far left, the gate at x = 0, the lanes beyond it.
const GATE = new Vector3(0, 8.5, 0);
const GATE_R = 12;
const DESK = new Vector3(30, 0, -27);
const SHIELD = new Vector3(-36, 8, 30);
const HOME_X0 = 44;
const HOME_Z0 = -19.5;
const CELL = 6.5;
const GATE_S = 0.45; // the fraction of a particle's life at which it crosses the gate

const RGB = {
  noor: [1, 0.827, 0.431],
  approve: [0.306, 0.902, 0.651],
  ask: [0.949, 0.647, 0.118],
  human: [0.557, 0.635, 1],
  reject: [1, 0.42, 0.506],
  white: [1, 0.97, 0.9],
} as const;
const LANE_RGB: Record<Lane, readonly number[]> = { approve: RGB.approve, ask: RGB.ask, human: RGB.human, reject: RGB.reject };

const at = (a: ArrayLike<number>, i: number): number => a[i] as number;
const smooth = (a: number, b: number, x: number): number => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const VERT = /* glsl */ `
  attribute vec4 aColor;
  attribute float aSize;
  uniform float uScale;
  uniform float uBoost;
  varying vec4 vColor;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = clamp(aSize * uBoost * uScale / max(-mv.z, 0.1), 0.0, 220.0);
    vColor = aColor;
  }
`;
const FRAG = /* glsl */ `
  varying vec4 vColor;
  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float d = length(p) * 2.0;
    if (d > 1.0) discard;
    float core = exp(-d * d * 10.0);
    float halo = exp(-d * 3.4) * 0.42 * (1.0 - d);
    float a = (core + halo) * vColor.a;
    gl_FragColor = vec4(vColor.rgb, a);
  }
`;

const GROUND_VERT = /* glsl */ `
  uniform float uTime;
  uniform float uPulse;
  varying float vA;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    float dist = length(position.xz - vec2(8.0, 0.0));
    float fall = 1.0 - smoothstep(30.0, 120.0, dist);
    float ring = fract(uTime * 0.06) * 150.0;
    float wave = exp(-pow((length(position.xz) - ring) / 7.0, 2.0)) * 0.22;
    vA = (0.075 + wave + 0.05 * uPulse * exp(-length(position.xz) / 38.0)) * fall;
  }
`;
const GROUND_FRAG = /* glsl */ `
  varying float vA;
  void main() { gl_FragColor = vec4(1.0, 0.83, 0.43, vA); }
`;

interface PointSet {
  points: Points;
  geom: BufferGeometry;
  mat: ShaderMaterial;
  pos: Float32Array;
  col: Float32Array;
  size: Float32Array;
  n: number;
}

function pointSet(n: number, scaleUniform: { value: number }, dynamic: boolean): PointSet {
  const geom = new BufferGeometry();
  const pos = new Float32Array(n * 3);
  const col = new Float32Array(n * 4);
  const size = new Float32Array(n);
  const p = new BufferAttribute(pos, 3);
  const c = new BufferAttribute(col, 4);
  const s = new BufferAttribute(size, 1);
  if (dynamic) {
    p.setUsage(DynamicDrawUsage);
    c.setUsage(DynamicDrawUsage);
    s.setUsage(DynamicDrawUsage);
  }
  geom.setAttribute('position', p);
  geom.setAttribute('aColor', c);
  geom.setAttribute('aSize', s);
  const mat = new ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: { uScale: scaleUniform, uBoost: { value: 1 } },
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: AdditiveBlending,
  });
  const points = new Points(geom, mat);
  points.frustumCulled = false;
  return { points, geom, mat, pos, col, size, n };
}

function setPoint(set: PointSet, i: number, x: number, y: number, z: number, rgb: readonly number[], a: number, size: number): void {
  set.pos[i * 3] = x;
  set.pos[i * 3 + 1] = y;
  set.pos[i * 3 + 2] = z;
  set.col[i * 4] = at(rgb, 0);
  set.col[i * 4 + 1] = at(rgb, 1);
  set.col[i * 4 + 2] = at(rgb, 2);
  set.col[i * 4 + 3] = a;
  set.size[i] = size;
}

/** Points along the outline of the eight-point star (two squares) in the local yz plane, for the gate and the shield. */
function starPoints(radius: number, step: number, plane: 'yz' | 'xy'): number[][] {
  const out: number[][] = [];
  for (const rot of [Math.PI / 4, 0]) {
    for (let k = 0; k < 4; k++) {
      const a0 = rot + (k * Math.PI) / 2;
      const a1 = a0 + Math.PI / 2;
      const x0 = Math.cos(a0) * radius;
      const y0 = Math.sin(a0) * radius;
      const x1 = Math.cos(a1) * radius;
      const y1 = Math.sin(a1) * radius;
      const len = Math.hypot(x1 - x0, y1 - y0);
      const m = Math.max(2, Math.round(len / step));
      for (let j = 0; j < m; j++) {
        const t = j / m;
        const u = x0 + (x1 - x0) * t;
        const v = y0 + (y1 - y0) * t;
        out.push(plane === 'yz' ? [0, v, u] : [u, v, 0]);
      }
    }
  }
  return out;
}

function hexPoints(radius: number, step: number): number[][] {
  const out: number[][] = [];
  for (let k = 0; k < 6; k++) {
    const a0 = Math.PI / 6 + (k * Math.PI) / 3;
    const a1 = a0 + Math.PI / 3;
    const x0 = Math.cos(a0) * radius;
    const y0 = Math.sin(a0) * radius;
    const x1 = Math.cos(a1) * radius;
    const y1 = Math.sin(a1) * radius;
    const m = Math.max(2, Math.round(radius / step));
    for (let j = 0; j < m; j++) out.push([x0 + (x1 - x0) * (j / m), y0 + (y1 - y0) * (j / m), 0]);
  }
  return out;
}

export function createScene(canvas: HTMLCanvasElement, host: HTMLElement, hooks: SceneHooks): SceneHandle {
  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: 'high-performance' });
  } catch (error) {
    hooks.onFail(String(error));
    return { setCases: () => undefined, setScamCount: () => undefined, dispose: () => undefined };
  }
  renderer.setClearColor(0x070b1d, 1);
  const scene = new Scene();
  const camera = new PerspectiveCamera(FOV, 16 / 9, 1, 900);
  const scale = { value: 800 };
  const disposables: { dispose: () => void }[] = [];

  // ---- ground: the star lattice -------------------------------------------------------------------------------------
  const ground = (() => {
    const segs: number[] = [];
    const spacing = 8;
    const r = 3.3;
    for (let cx = -112; cx <= 112; cx += spacing) {
      for (let cz = -72; cz <= 72; cz += spacing) {
        for (const rot of [Math.PI / 4, 0]) {
          for (let k = 0; k < 4; k++) {
            const a0 = rot + (k * Math.PI) / 2;
            const a1 = a0 + Math.PI / 2;
            segs.push(cx + Math.cos(a0) * r, 0, cz + Math.sin(a0) * r, cx + Math.cos(a1) * r, 0, cz + Math.sin(a1) * r);
          }
        }
      }
    }
    const geom = new BufferGeometry();
    geom.setAttribute('position', new BufferAttribute(new Float32Array(segs), 3));
    const mat = new ShaderMaterial({
      vertexShader: GROUND_VERT,
      fragmentShader: GROUND_FRAG,
      uniforms: { uTime: { value: 0 }, uPulse: { value: 0 } },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: AdditiveBlending,
    });
    const lines = new LineSegments(geom, mat);
    lines.frustumCulled = false;
    scene.add(lines);
    disposables.push(geom, mat);
    return mat;
  })();

  // ---- far stars ----------------------------------------------------------------------------------------------------
  const stars = (() => {
    const rand = rng(7);
    const n = 420;
    const arr = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const th = rand() * Math.PI * 2;
      const ph = Math.acos(0.15 + rand() * 0.85);
      const rad = 520;
      arr[i * 3] = Math.cos(th) * Math.sin(ph) * rad;
      arr[i * 3 + 1] = Math.cos(ph) * rad;
      arr[i * 3 + 2] = Math.sin(th) * Math.sin(ph) * rad;
    }
    const geom = new BufferGeometry();
    geom.setAttribute('position', new BufferAttribute(arr, 3));
    const mat = new PointsMaterial({ color: 0xa7aed6, size: 1.7, sizeAttenuation: false, transparent: true, opacity: 0.55, depthWrite: false });
    const pts = new Points(geom, mat);
    pts.frustumCulled = false;
    scene.add(pts);
    disposables.push(geom, mat);
    return pts;
  })();

  // ---- the dark horizon: where the light comes from ------------------------------------------------------------------
  const horizon = pointSet(34, scale, false);
  for (let i = 0; i < horizon.n; i++) {
    const z = -52 + (i / (horizon.n - 1)) * 104;
    setPoint(horizon, i, -104, 1.5, z, RGB.noor, 0.035, 60 + (i % 3) * 14);
  }
  scene.add(horizon.points);
  disposables.push(horizon.geom, horizon.mat);

  // ---- the gate: the cost-matrix decision, an eight-point star ---------------------------------------------------------
  const gateGroup = new Group();
  gateGroup.position.copy(GATE);
  const gateOutline = starPoints(GATE_R, 0.32, 'yz');
  const gate = pointSet(gateOutline.length + 1, scale, false);
  gateOutline.forEach((p, i) => setPoint(gate, i, at(p, 0), at(p, 1), at(p, 2), RGB.noor, 0.85, 0.55));
  setPoint(gate, gateOutline.length, 0, 0, 0, RGB.noor, 0.14, 44);
  gateGroup.add(gate.points);
  const gateInner = starPoints(GATE_R * 0.5, 0.4, 'yz');
  const gate2 = pointSet(gateInner.length, scale, false);
  gateInner.forEach((p, i) => setPoint(gate2, i, at(p, 0), at(p, 1), at(p, 2), RGB.white, 0.5, 0.3));
  gateGroup.add(gate2.points);
  scene.add(gateGroup);
  disposables.push(gate.geom, gate.mat, gate2.geom, gate2.mat);

  // ---- the homes: a lattice of small stars --------------------------------------------------------------------------------
  const homePos: number[] = [];
  const lines: number[] = [];
  for (let cx = 0; cx < 6; cx++) {
    for (let cz = 0; cz < 7; cz++) {
      const ox = HOME_X0 + cx * CELL;
      const oz = HOME_Z0 + cz * CELL;
      homePos.push(ox, 0.4, oz);
      const ring: number[][] = [];
      for (let k = 0; k < 8; k++) {
        const tip = (k * Math.PI) / 4;
        const inner = tip + Math.PI / 8;
        homePos.push(ox + Math.cos(tip) * 2.2, 0.4, oz + Math.sin(tip) * 2.2);
        homePos.push(ox + Math.cos(inner) * 1.05, 0.4, oz + Math.sin(inner) * 1.05);
        ring.push([ox + Math.cos(tip) * 2.2, oz + Math.sin(tip) * 2.2], [ox + Math.cos(inner) * 1.05, oz + Math.sin(inner) * 1.05]);
      }
      for (let k = 0; k < ring.length; k++) {
        const a = ring[k] as number[];
        const b = ring[(k + 1) % ring.length] as number[];
        lines.push(at(a, 0), 0.3, at(a, 1), at(b, 0), 0.3, at(b, 1));
      }
    }
  }
  const nHomes = homePos.length / 3;
  const homes = pointSet(nHomes, scale, true);
  const light = new Float32Array(nHomes);
  for (let i = 0; i < nHomes; i++) homes.pos.set(homePos.slice(i * 3, i * 3 + 3), i * 3);
  scene.add(homes.points);
  disposables.push(homes.geom, homes.mat);
  const homeLinesGeom = new BufferGeometry();
  homeLinesGeom.setAttribute('position', new BufferAttribute(new Float32Array(lines), 3));
  const homeLinesMat = new ShaderMaterial({
    vertexShader: 'void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader: 'void main(){gl_FragColor=vec4(0.31,0.9,0.65,0.07);}',
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: AdditiveBlending,
  });
  const homeLines = new LineSegments(homeLinesGeom, homeLinesMat);
  homeLines.frustumCulled = false;
  scene.add(homeLines);
  disposables.push(homeLinesGeom, homeLinesMat);

  // ---- the human desk -------------------------------------------------------------------------------------------------------
  const desk = pointSet(90, scale, true);
  const deskRand = rng(21);
  for (let i = 0; i < desk.n; i++) {
    const ring = i < 36;
    const ang = ring ? (i / 36) * Math.PI * 2 : deskRand() * Math.PI * 2;
    const rad = ring ? 6.2 : Math.sqrt(deskRand()) * 4.6;
    desk.pos[i * 3] = DESK.x + Math.cos(ang) * rad;
    desk.pos[i * 3 + 1] = 0.5 + (ring ? 0 : deskRand() * 1.4);
    desk.pos[i * 3 + 2] = DESK.z + Math.sin(ang) * rad;
  }
  scene.add(desk.points);
  disposables.push(desk.geom, desk.mat);
  const deskHalo = pointSet(2, scale, true);
  setPoint(deskHalo, 0, DESK.x, 2, DESK.z, RGB.human, 0.12, 62);
  setPoint(deskHalo, 1, DESK.x, 2.4, DESK.z, RGB.human, 0.1, 30);
  scene.add(deskHalo.points);
  disposables.push(deskHalo.geom, deskHalo.mat);

  // ---- the scam shield and its sparks ---------------------------------------------------------------------------------------
  const shieldGroup = new Group();
  shieldGroup.position.copy(SHIELD);
  shieldGroup.rotation.y = 1.25;
  const hex = hexPoints(9, 0.34);
  const shieldStar = starPoints(4.6, 0.34, 'xy');
  const shield = pointSet(hex.length + shieldStar.length + 1, scale, true);
  hex.forEach((p, i) => setPoint(shield, i, at(p, 0), at(p, 1), at(p, 2), RGB.reject, 0.75, 0.4));
  shieldStar.forEach((p, i) => setPoint(shield, hex.length + i, at(p, 0), at(p, 1), at(p, 2), RGB.reject, 0.55, 0.3));
  setPoint(shield, shield.n - 1, 0, 0, 0, RGB.reject, 0.14, 40);
  shieldGroup.add(shield.points);
  scene.add(shieldGroup);
  disposables.push(shield.geom, shield.mat);

  const sparks = pointSet(MAX_SPARKS, scale, true);
  const sparkRand = rng(99);
  const sparkP = new Float32Array(MAX_SPARKS * 10); // spawn xyz, scatter velocity xyz, period, phase, seed, size
  for (let i = 0; i < MAX_SPARKS; i++) {
    const th = sparkRand() * Math.PI * 2;
    const el = (sparkRand() - 0.2) * 1.1;
    const far = 34 + sparkRand() * 26;
    sparkP[i * 10] = SHIELD.x + Math.cos(th) * Math.cos(el) * far * 1.1;
    sparkP[i * 10 + 1] = Math.max(2, SHIELD.y + Math.sin(el) * far * 0.6);
    sparkP[i * 10 + 2] = SHIELD.z + Math.sin(th) * Math.cos(el) * far * 0.8 + 10;
    const ang = sparkRand() * Math.PI * 2;
    const mag = 8 + sparkRand() * 16;
    sparkP[i * 10 + 3] = Math.cos(ang) * mag;
    sparkP[i * 10 + 4] = 4 + sparkRand() * 14;
    sparkP[i * 10 + 5] = Math.sin(ang) * mag * 0.8 + 6;
    sparkP[i * 10 + 6] = 4.2 + sparkRand() * 3.2;
    sparkP[i * 10 + 7] = sparkRand();
    sparkP[i * 10 + 8] = sparkRand();
    sparkP[i * 10 + 9] = 0.35 + sparkRand() * 0.35;
  }
  let sparkCount = 0;
  scene.add(sparks.points);
  disposables.push(sparks.geom, sparks.mat);

  // ---- the particles: one synthetic labelled case each ---------------------------------------------------------------------------
  const particles = pointSet(MAX_PARTICLES, scale, true);
  scene.add(particles.points);
  disposables.push(particles.geom, particles.mat);
  let n = 0;
  let cases: readonly ReplayCase[] = [];
  const caseOf = new Int32Array(MAX_PARTICLES);
  const laneIdx = new Uint8Array(MAX_PARTICLES);
  const homeOf = new Int32Array(MAX_PARTICLES);
  const period = new Float32Array(MAX_PARTICLES);
  const phase = new Float32Array(MAX_PARTICLES);
  const prevS = new Float32Array(MAX_PARTICLES);
  const seedOf = new Float32Array(MAX_PARTICLES);
  const baseSize = new Float32Array(MAX_PARTICLES);
  const path = new Float32Array(MAX_PARTICLES * 15); // start xyz, gate point xyz, bezier controls 1..3
  const LANES: Lane[] = ['approve', 'ask', 'human', 'reject'];
  const LANE_ALPHA = [0.95, 0.85, 0.5, 0.7] as const;

  function build(next: readonly ReplayCase[]): void {
    cases = next;
    const count = next.length;
    n = count === 0 ? 0 : Math.min(MAX_PARTICLES, count * Math.max(1, Math.floor(MAX_PARTICLES / count)));
    const rand = rng(1234);
    const ribbons = 9;
    for (let i = 0; i < n; i++) {
      const c = next[i % count] as ReplayCase;
      const lane = laneOf(c);
      caseOf[i] = i % count;
      laneIdx[i] = LANES.indexOf(lane);
      period[i] = 11 + rand() * 5;
      phase[i] = rand();
      prevS[i] = -1;
      seedOf[i] = rand() * 6.283;
      baseSize[i] = 0.85 + rand() * 0.6;
      const rb = Math.floor(rand() * ribbons);
      const rz = -34 + (rb / (ribbons - 1)) * 68;
      const ry = 3 + ((rb * 5) % 9) * 1.5;
      const gauss = () => (rand() + rand() + rand() - 1.5) * 2;
      const b = i * 15;
      path[b] = -98 - rand() * 8;
      path[b + 1] = Math.max(0.6, ry + gauss() * 1.4);
      path[b + 2] = rz + gauss() * 1.6;
      path[b + 3] = 0;
      path[b + 4] = GATE.y + gauss() * 3.2;
      path[b + 5] = gauss() * 3.6;
      const side = rand() < 0.5 ? -1 : 1;
      const gy = at(path, b + 4);
      const gz = at(path, b + 5);
      let t: number[];
      homeOf[i] = -1;
      if (lane === 'approve') {
        const h = Math.floor(rand() * nHomes);
        homeOf[i] = h;
        const tx = at(homePos, h * 3);
        const tz = at(homePos, h * 3 + 2);
        t = [14 + rand() * 6, gy + 5 + rand() * 7, gz + (tz - gz) * 0.2, tx - 9, 11 + rand() * 7, tz + gauss() * 2, tx, 0.5, tz];
      } else if (lane === 'ask') {
        t = [34 + rand() * 12, 10 + rand() * 6, gz + side * (8 + rand() * 8), 24 + rand() * 12, 34 + rand() * 10, side * (24 + rand() * 12), -34 + rand() * 12, 13 + rand() * 6, side * (18 + rand() * 10)];
      } else if (lane === 'human') {
        const a = rand() * 6.283;
        const r = Math.sqrt(rand()) * 4.4;
        t = [12 + rand() * 4, gy - 1, gz - 9 - rand() * 6, DESK.x - 4, 7 + rand() * 4, DESK.z + 7, DESK.x + Math.cos(a) * r, 0.8 + rand() * 1.2, DESK.z + Math.sin(a) * r];
      } else {
        const tz = 36 + rand() * 5;
        t = [16 + rand() * 4, gy - 3, gz + 10, 34 + rand() * 6, 3 + rand() * 2, tz - 10, 46 + rand() * 4, 0.8, tz];
      }
      for (let k = 0; k < 9; k++) path[b + 6 + k] = at(t, k);
    }
    particles.geom.setDrawRange(0, n);
  }

  // ---- camera ----------------------------------------------------------------------------------------------------------------------
  const target = new Vector3(22, 3, 4);
  let az = 1.1;
  let pol = 1.2;
  let dist = 126;
  let lastInteract = -1e9;
  let drift = 0;
  const camPos = new Vector3();
  let aspect = 16 / 9;

  function placeCamera(now: number): void {
    const fit = Math.max(1, 0.9 / aspect);
    const azE = az + drift * 0.2 * Math.sin(now * 0.05);
    const distE = dist * fit * (1 + drift * 0.035 * Math.sin(now * 0.037));
    const polE = pol + drift * 0.03 * Math.sin(now * 0.041);
    camPos.set(
      target.x + distE * Math.sin(polE) * Math.sin(azE),
      target.y + distE * Math.cos(polE),
      target.z + distE * Math.sin(polE) * Math.cos(azE),
    );
    camera.position.copy(camPos);
    camera.lookAt(target);
    camera.updateMatrixWorld();
  }

  function resize(): void {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    aspect = w / h;
    camera.aspect = aspect;
    // portrait: lift the scene above the numbers that sit at the bottom of the screen
    if (aspect < 1) camera.setViewOffset(w, h, 0, h * 0.14, w, h);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    scale.value = (renderer.domElement.height * 0.5) / Math.tan((FOV * Math.PI) / 360);
  }
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  // ---- pointer: orbit, pinch, wheel, hover ----------------------------------------------------------------------------------------------
  const pointers = new Map<number, { x: number; y: number }>();
  let pinchStart = 0;
  let distStart = 0;
  let moved = 0;
  let hovered = -1;
  let hoverPending: { x: number; y: number } | null = null;
  const touch = () => {
    lastInteract = performance.now() / 1000;
  };

  function pick(px: number, py: number): number {
    const rect = canvas.getBoundingClientRect();
    const v = new Vector3();
    let best = -1;
    let bestD = 18 * 18;
    for (let i = 0; i < n; i++) {
      if (at(particles.col, i * 4 + 3) < 0.25) continue;
      v.set(at(particles.pos, i * 3), at(particles.pos, i * 3 + 1), at(particles.pos, i * 3 + 2)).project(camera);
      if (v.z > 1) continue;
      const sx = (v.x * 0.5 + 0.5) * rect.width + rect.left;
      const sy = (-v.y * 0.5 + 0.5) * rect.height + rect.top;
      const d = (sx - px) * (sx - px) + (sy - py) * (sy - py);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  function showHover(px: number, py: number): void {
    const i = pick(px, py);
    hovered = i;
    if (i < 0) return hooks.onHover(null);
    const c = cases[at(caseOf, i)] as ReplayCase;
    hooks.onHover({ c, lane: laneOf(c), x: px, y: py });
  }

  const onDown = (e: PointerEvent) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved = 0;
    touch();
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
      pinchStart = Math.hypot(a.x - b.x, a.y - b.y);
      distStart = dist;
    }
  };
  const onMove = (e: PointerEvent) => {
    const p = pointers.get(e.pointerId);
    if (!p) {
      hoverPending = { x: e.clientX, y: e.clientY };
      return;
    }
    touch();
    if (pointers.size === 1) {
      const dx = e.clientX - p.x;
      const dy = e.clientY - p.y;
      moved += Math.abs(dx) + Math.abs(dy);
      az -= dx * 0.005;
      pol = Math.min(1.45, Math.max(0.3, pol - dy * 0.004));
    }
    p.x = e.clientX;
    p.y = e.clientY;
    if (pointers.size === 2 && pinchStart > 0) {
      const [a, b] = [...pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
      dist = Math.min(180, Math.max(40, (distStart * pinchStart) / Math.max(10, Math.hypot(a.x - b.x, a.y - b.y))));
      moved += 20;
    }
  };
  const onUp = (e: PointerEvent) => {
    const wasTap = pointers.size === 1 && moved < 8;
    pointers.delete(e.pointerId);
    pinchStart = 0;
    if (wasTap) showHover(e.clientX, e.clientY);
  };
  const onLeave = () => {
    hoverPending = null;
    hovered = -1;
    hooks.onHover(null);
  };
  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    touch();
    dist = Math.min(180, Math.max(40, dist * Math.exp(e.deltaY * 0.0012)));
  };
  const onKey = (e: KeyboardEvent) => {
    const step = 0.08;
    if (e.key === 'ArrowLeft') az += step;
    else if (e.key === 'ArrowRight') az -= step;
    else if (e.key === 'ArrowUp') pol = Math.max(0.3, pol - step);
    else if (e.key === 'ArrowDown') pol = Math.min(1.45, pol + step);
    else if (e.key === '+' || e.key === '=') dist = Math.max(40, dist * 0.92);
    else if (e.key === '-' || e.key === '_') dist = Math.min(180, dist * 1.08);
    else return;
    e.preventDefault();
    touch();
  };
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointerleave', onLeave);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('keydown', onKey);

  // ---- the frame loop --------------------------------------------------------------------------------------------------------------------------------
  const labelDefs: { id: string; p: Vector3 }[] = [
    { id: 'horizon', p: new Vector3(-104, 7, 0) },
    { id: 'gate', p: new Vector3(0, GATE.y + GATE_R + 3, 0) },
    { id: 'homes', p: new Vector3(HOME_X0 + 16, 6, HOME_Z0 - 4) },
    { id: 'desk', p: new Vector3(DESK.x, 9, DESK.z) },
    { id: 'shield', p: new Vector3(SHIELD.x, SHIELD.y + 11, SHIELD.z) },
  ];
  const tmp = new Vector3();
  let raf = 0;
  let running = true;
  let last = performance.now() / 1000;
  let clock = 0;
  let pulse = 0;
  let deskGlow = 0;
  let labelTick = 0;

  const perf = window.location.search.includes('perf') ? { frames: 0, jsMs: 0, renderMs: 0 } : null;
  if (perf) (window as unknown as { __loomPerf: typeof perf }).__loomPerf = perf;

  function frame(): void {
    raf = 0;
    if (!running) return;
    const t0 = perf ? performance.now() : 0;
    const nowS = performance.now() / 1000;
    const dt = Math.min(0.05, Math.max(0.001, nowS - last));
    last = nowS;
    clock += dt;

    // idle drift eases in after 5 s of no interaction
    drift += ((nowS - lastInteract > 5 ? 1 : 0) - drift) * Math.min(1, dt * 0.8);
    placeCamera(clock);

    let gateHits = 0;
    let deskHits = 0;
    const { pos, col, size } = particles;
    const hoverI = hovered;
    for (let i = 0; i < n; i++) {
      const ph = at(phase, i) + clock / at(period, i);
      const s = ph - Math.floor(ph);
      const ps = at(prevS, i);
      const lane = at(laneIdx, i);
      if (ps >= 0 && ps < GATE_S && s >= GATE_S) gateHits++;
      if (ps >= 0 && ps < 0.97 && s >= 0.97) {
        if (lane === 0) light[at(homeOf, i)] = Math.min(1.2, at(light, at(homeOf, i)) + 0.45);
        else if (lane === 2) deskHits++;
      }
      prevS[i] = s;
      const c = cases[at(caseOf, i)] as ReplayCase;
      const b = i * 15;
      let x: number;
      let y: number;
      let z: number;
      if (s < GATE_S) {
        const u = s / GATE_S;
        const e = Math.pow(u, 1.7);
        const wob = Math.sin(u * 9 + at(seedOf, i)) * 1.5 * (1 - u);
        x = at(path, b) + (at(path, b + 3) - at(path, b)) * e;
        y = at(path, b + 1) + (at(path, b + 4) - at(path, b + 1)) * e + wob * 0.6;
        z = at(path, b + 2) + (at(path, b + 5) - at(path, b + 2)) * e + wob;
      } else {
        const u = (s - GATE_S) / (1 - GATE_S);
        const e = u * u * (3 - 2 * u) * 0.6 + u * 0.4;
        const m = 1 - e;
        const w0 = m * m * m;
        const w1 = 3 * m * m * e;
        const w2 = 3 * m * e * e;
        const w3 = e * e * e;
        x = w0 * at(path, b + 3) + w1 * at(path, b + 6) + w2 * at(path, b + 9) + w3 * at(path, b + 12);
        y = w0 * at(path, b + 4) + w1 * at(path, b + 7) + w2 * at(path, b + 10) + w3 * at(path, b + 13);
        z = w0 * at(path, b + 5) + w1 * at(path, b + 8) + w2 * at(path, b + 11) + w3 * at(path, b + 14);
      }
      const mix = smooth(0.4, 0.5, s);
      const lc = LANE_RGB[LANES[lane] as Lane] as readonly number[];
      const bright = 0.5 + 0.5 * c.p_ok;
      const flash = Math.exp(-Math.pow((s - GATE_S) / 0.02, 2));
      let r = (RGB.noor[0] * bright) * (1 - mix) + at(lc, 0) * mix;
      let g = (RGB.noor[1] * bright) * (1 - mix) + at(lc, 1) * mix;
      let bl = (RGB.noor[2] * bright) * (1 - mix) + at(lc, 2) * mix;
      r += flash * 0.22;
      g += flash * 0.22;
      bl += flash * 0.22;
      let a = smooth(0, 0.07, s) * (1 - smooth(0.93, 1, s)) * (LANE_ALPHA[lane] ?? 0.8) * (s < GATE_S ? 0.7 : 1);
      let sz = at(baseSize, i) * (lane === 3 ? 0.62 : 1) * (1 + flash * 0.7);
      if (i === hoverI) {
        a = 1;
        sz *= 3.2;
      }
      pos[i * 3] = x;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = z;
      col[i * 4] = r;
      col[i * 4 + 1] = g;
      col[i * 4 + 2] = bl;
      col[i * 4 + 3] = a;
      size[i] = sz;
    }
    particles.geom.attributes.position!.needsUpdate = true;
    particles.geom.attributes.aColor!.needsUpdate = true;
    particles.geom.attributes.aSize!.needsUpdate = true;

    // gate energy follows how many cases crossed it in the last moments
    pulse += (Math.min(1, (gateHits / Math.max(dt, 0.001)) / 260) - pulse) * Math.min(1, dt * 3);
    gate.mat.uniforms.uBoost!.value = 1 + pulse * 0.9;
    gate2.mat.uniforms.uBoost!.value = 1 + pulse * 0.7;
    gateGroup.rotation.x = clock * 0.07;
    gate2.points.rotation.x = -clock * 0.18;
    (ground.uniforms.uTime as { value: number }).value = clock;
    (ground.uniforms.uPulse as { value: number }).value = pulse;

    // homes: brighten as payments land, fade slowly back to a faint glow
    for (let i = 0; i < nHomes; i++) {
      const l = Math.max(0, at(light, i) - dt * 0.35);
      light[i] = l;
      const k = Math.min(1, l);
      homes.col[i * 4] = 0.306 + (1 - 0.306) * k * 0.9;
      homes.col[i * 4 + 1] = 0.7 + 0.3 * k;
      homes.col[i * 4 + 2] = 0.5 + 0.1 * k;
      homes.col[i * 4 + 3] = 0.16 + 0.8 * k;
      homes.size[i] = 0.5 + 0.9 * k;
    }
    homes.geom.attributes.aColor!.needsUpdate = true;
    homes.geom.attributes.aSize!.needsUpdate = true;
    homes.geom.attributes.position!.needsUpdate = false;

    // desk: soft halo that breathes and warms with arrivals
    deskGlow = Math.min(1.5, deskGlow * Math.exp(-dt * 0.6) + deskHits * 0.03);
    for (let i = 0; i < desk.n; i++) {
      const tw = 0.5 + 0.5 * Math.sin(clock * 1.3 + i * 1.7);
      const ring = i < 36;
      desk.col[i * 4] = RGB.human[0];
      desk.col[i * 4 + 1] = RGB.human[1];
      desk.col[i * 4 + 2] = RGB.human[2];
      desk.col[i * 4 + 3] = (ring ? 0.4 : 0.2 + 0.25 * tw) + Math.min(0.4, deskGlow * 0.3);
      desk.size[i] = ring ? 0.5 : 0.4 + 0.2 * tw;
    }
    desk.geom.attributes.aColor!.needsUpdate = true;
    desk.geom.attributes.aSize!.needsUpdate = true;
    deskHalo.col[3] = 0.1 + 0.05 * Math.sin(clock * 0.9) + Math.min(0.14, deskGlow * 0.08);
    deskHalo.geom.attributes.aColor!.needsUpdate = true;

    // sparks strike the shield and scatter
    let strikes = 0;
    for (let i = 0; i < sparkCount; i++) {
      const o = i * 10;
      const ph = at(sparkP, o + 7) + clock / at(sparkP, o + 6);
      const s = ph - Math.floor(ph);
      let x: number;
      let y: number;
      let z: number;
      let a: number;
      if (s < 0.55) {
        const u = Math.pow(s / 0.55, 1.5);
        x = at(sparkP, o) + (SHIELD.x - at(sparkP, o)) * u;
        y = at(sparkP, o + 1) + (SHIELD.y - at(sparkP, o + 1)) * u;
        z = at(sparkP, o + 2) + (SHIELD.z - at(sparkP, o + 2)) * u;
        a = 0.75 * smooth(0, 0.1, s);
      } else {
        const tau = ((s - 0.55) / 0.45) * 1.3;
        const drag = 1 - Math.exp(-tau * 2.2);
        x = SHIELD.x + at(sparkP, o + 3) * drag * 0.6;
        y = Math.max(0.3, SHIELD.y + at(sparkP, o + 4) * drag * 0.6 - 9 * tau * tau);
        z = SHIELD.z + at(sparkP, o + 5) * drag * 0.6;
        a = 0.95 * (1 - smooth(0.55, 1, s));
        if (s < 0.57) strikes++;
      }
      setPoint(sparks, i, x, y, z, RGB.reject, a, at(sparkP, o + 9) * (s >= 0.55 && s < 0.6 ? 2.6 : 1));
    }
    sparks.geom.attributes.position!.needsUpdate = true;
    sparks.geom.attributes.aColor!.needsUpdate = true;
    sparks.geom.attributes.aSize!.needsUpdate = true;
    shield.col[(shield.n - 1) * 4 + 3] = 0.1 + Math.min(0.3, strikes * 0.05) + 0.03 * Math.sin(clock * 2);
    shield.geom.attributes.aColor!.needsUpdate = true;
    shieldGroup.rotation.y = 1.25 + Math.sin(clock * 0.3) * 0.06;
    stars.rotation.y = clock * 0.002;

    if (hoverPending) {
      const p = hoverPending;
      hoverPending = null;
      if (pointers.size === 0) showHover(p.x, p.y);
    }

    const t1 = perf ? performance.now() : 0;
    renderer.render(scene, camera);
    if (perf) {
      perf.frames++;
      perf.jsMs += t1 - t0;
      perf.renderMs += performance.now() - t1;
    }

    // labels: updated a few times a second, never per frame
    labelTick += dt;
    if (labelTick > 0.08) {
      labelTick = 0;
      const rect = canvas.getBoundingClientRect();
      hooks.onLabels(
        labelDefs.map((d) => {
          tmp.copy(d.p).project(camera);
          return { id: d.id, x: (tmp.x * 0.5 + 0.5) * rect.width, y: (-tmp.y * 0.5 + 0.5) * rect.height, visible: tmp.z < 1 && Math.abs(tmp.x) < 1.05 && Math.abs(tmp.y) < 1.05 };
        }),
      );
    }
    raf = requestAnimationFrame(frame);
  }

  const onVisibility = () => {
    if (document.hidden) {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    } else if (!running) {
      running = true;
      last = performance.now() / 1000;
      raf = requestAnimationFrame(frame);
    }
  };
  document.addEventListener('visibilitychange', onVisibility);
  const onContextLost = (e: Event) => {
    e.preventDefault();
    hooks.onFail('webgl context lost');
  };
  canvas.addEventListener('webglcontextlost', onContextLost);

  raf = requestAnimationFrame(frame);

  return {
    setCases(next) {
      build(next);
      hovered = -1;
      hooks.onHover(null);
    },
    setScamCount(count) {
      sparkCount = Math.min(MAX_SPARKS, Math.max(30, count));
      sparks.geom.setDrawRange(0, sparkCount);
    },
    dispose() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('keydown', onKey);
      for (const d of disposables) d.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
