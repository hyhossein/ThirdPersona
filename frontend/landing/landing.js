/* ============================================================
   THIRDPERSONA — layered scroll landing
   Layers (back → front):
     0. hue-shifting deep-space gradient (CSS vars, scroll-driven)
     1. starfield (slowest parallax, WebGL)
     2. the human point-cloud (forms from dust as you scroll)
     3. constellation lines (brighten with understanding)
     4. HTML content layers, each at its own parallax depth
     5. grain + vignette
   Story: dust → noticing → consent → you.
   ============================================================ */

import * as THREE from "three";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import Lenis from "lenis";

gsap.registerPlugin(ScrollTrigger, SplitText);

/* ---------- smooth scroll ---------- */
const lenis = new Lenis({ lerp: 0.09 });
lenis.on("scroll", ScrollTrigger.update);
gsap.ticker.add((t) => lenis.raf(t * 1000));
gsap.ticker.lagSmoothing(0);

/* ---------- deterministic helpers ---------- */
function seededRandom(seed) {
  let s = seed;
  return () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
}
function generateBustPoints(N, seed) {
  const rng = seededRandom(seed);
  const pts = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const region = rng();
    let x, y, z;
    if (region < 0.55) {
      let u = rng() * 2 - 1, theta = rng() * Math.PI * 2;
      const sq = Math.sqrt(1 - u * u);
      x = sq * Math.cos(theta) * 0.36;
      y = u * 0.45 + 0.55;
      z = sq * Math.sin(theta) * 0.33;
      if (y < 0.45 && z > 0) { x *= 0.82; z *= 0.9; }
      if (z > 0.18) z *= 0.92;
      if (z > 0.24 && y > 0.55 && y < 0.68) z += 0.015;
      if (z > 0.28 && Math.abs(x) < 0.05 && y > 0.45 && y < 0.58) z += 0.03;
    } else if (region < 0.68) {
      const theta = rng() * Math.PI * 2;
      y = 0.06 + rng() * 0.18;
      const r = 0.125 + (rng() - 0.5) * 0.015;
      x = Math.cos(theta) * r; z = Math.sin(theta) * r * 0.9;
    } else {
      const t = rng();
      y = 0.06 - t * 0.56;
      const flare = 0.14 + Math.pow(t, 0.65) * 0.6;
      const theta = rng() * Math.PI * 2;
      x = Math.cos(theta) * flare * 1.25; z = Math.sin(theta) * flare * 0.55;
    }
    pts[i * 3] = x + (rng() - 0.5) * 0.012;
    pts[i * 3 + 1] = y + (rng() - 0.5) * 0.012;
    pts[i * 3 + 2] = z + (rng() - 0.5) * 0.012;
  }
  return pts;
}
function makeSprite() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.55)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

/* ---------- scroll-driven state (single source of truth) ---------- */
const P = {
  coverage: 0.05,   // how much of the human exists
  lines: 0.0,       // constellation line opacity
  rotBoost: 0,      // extra rotation from scroll
  camZ: 2.9,
  camY: 0.25,
  glow: 0,          // consent-moment pulse
  warmth: 0,        // 0 = cold space, 1 = warm gold ambience
};

/* ---------- three.js scene ---------- */
const canvas = document.getElementById("gl");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, P.camY, P.camZ);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);

const sprite = makeSprite();
const group = new THREE.Group();
scene.add(group);

const N = 2200, SEED = 99173;
const targets = generateBustPoints(N, SEED);
const dust = new Float32Array(N * 3);
const cur = new Float32Array(N * 3);
const rng = seededRandom(SEED + 1);
for (let i = 0; i < N; i++) {
  const r = 1.9 + rng() * 1.8;
  const u = rng() * 2 - 1, th = rng() * Math.PI * 2;
  const sq = Math.sqrt(1 - u * u);
  dust[i * 3] = sq * Math.cos(th) * r;
  dust[i * 3 + 1] = u * r * 0.7 + 0.1;
  dust[i * 3 + 2] = sq * Math.sin(th) * r;
  cur.set(dust.subarray(i * 3, i * 3 + 3), i * 3);
}
const colors = new Float32Array(N * 3);
const GOLD = new THREE.Color("#E3B564"), BLUE = new THREE.Color("#8D9EF0"), DIM = new THREE.Color("#232B3E");
const isGold = new Uint8Array(N);
for (let i = 0; i < N; i++) { isGold[i] = rng() > 0.62 ? 1 : 0; DIM.toArray(colors, i * 3); }

const geo = new THREE.BufferGeometry();
geo.setAttribute("position", new THREE.BufferAttribute(cur, 3));
geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
group.add(new THREE.Points(geo, new THREE.PointsMaterial({
  size: 0.032, vertexColors: true, map: sprite, transparent: true,
  opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
})));

/* starfield — slowest layer */
const NS = 900, sPos = new Float32Array(NS * 3), srng = seededRandom(SEED + 31);
for (let i = 0; i < NS; i++) {
  const r = 3.4 + srng() * 5.5, u = srng() * 2 - 1, th = srng() * Math.PI * 2;
  const sq = Math.sqrt(1 - u * u);
  sPos[i * 3] = sq * Math.cos(th) * r; sPos[i * 3 + 1] = u * r * 0.6 + 0.1; sPos[i * 3 + 2] = sq * Math.sin(th) * r;
}
const starGeo = new THREE.BufferGeometry();
starGeo.setAttribute("position", new THREE.BufferAttribute(sPos, 3));
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
  size: 0.016, color: 0x2c3854, map: sprite, transparent: true, opacity: 0.75,
  depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
}));
scene.add(stars);

/* constellation lines */
const pairs = [];
{
  const cell = new Map();
  const key = (x, y, z) => `${Math.floor(x / 0.14)},${Math.floor(y / 0.14)},${Math.floor(z / 0.14)}`;
  for (let i = 0; i < N; i++) {
    const k = key(targets[i * 3], targets[i * 3 + 1], targets[i * 3 + 2]);
    if (!cell.has(k)) cell.set(k, []);
    cell.get(k).push(i);
  }
  for (let i = 0; i < N && pairs.length < 3000; i++) {
    const x = targets[i * 3], y = targets[i * 3 + 1], z = targets[i * 3 + 2];
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      const bucket = cell.get(`${Math.floor(x / 0.14) + dx},${Math.floor(y / 0.14) + dy},${Math.floor(z / 0.14) + dz}`);
      if (!bucket) continue;
      for (const j of bucket) {
        if (j <= i) continue;
        const ddx = targets[j * 3] - x, ddy = targets[j * 3 + 1] - y, ddz = targets[j * 3 + 2] - z;
        if (ddx * ddx + ddy * ddy + ddz * ddz < 0.0121) pairs.push([i, j, Math.max(i, j)]);
      }
    }
  }
  pairs.sort((a, b) => a[2] - b[2]);
}
const lPos = new Float32Array(pairs.length * 6);
const lCol = new Float32Array(pairs.length * 6);
const lineGeo = new THREE.BufferGeometry();
lineGeo.setAttribute("position", new THREE.BufferAttribute(lPos, 3));
lineGeo.setAttribute("color", new THREE.BufferAttribute(lCol, 3));
const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending });
group.add(new THREE.LineSegments(lineGeo, lineMat));

/* pointer parallax */
let px = 0, py = 0;
addEventListener("pointermove", (e) => {
  px = (e.clientX / innerWidth - 0.5) * 2;
  py = (e.clientY / innerHeight - 0.5) * 2;
});

/* render loop */
let t = 0;
const tmp = new THREE.Color(), WHITE = new THREE.Color("#FFFFFF");
function frame() {
  t += 0.008;
  group.rotation.y = t * 0.28 + P.rotBoost;
  stars.rotation.y = t * 0.02 + P.rotBoost * 0.12; // slowest layer
  camera.position.x += (px * 0.09 - camera.position.x) * 0.03;
  camera.position.y += (P.camY - py * 0.05 - camera.position.y) * 0.03;
  camera.position.z += (P.camZ - camera.position.z) * 0.05;
  camera.lookAt(0, 0.15, 0);

  const revealed = Math.floor(N * Math.min(1, Math.max(0, P.coverage)));
  for (let i = 0; i < N; i++) {
    const i3 = i * 3;
    if (i < revealed) {
      const bx = targets[i3] + Math.sin(t * 1.4 + i) * 0.004;
      const by = targets[i3 + 1] + Math.cos(t * 1.2 + i) * 0.004;
      const bz = targets[i3 + 2] + Math.sin(t * 1.1 + i * 0.7) * 0.004;
      cur[i3] += (bx - cur[i3]) * 0.05;
      cur[i3 + 1] += (by - cur[i3 + 1]) * 0.05;
      cur[i3 + 2] += (bz - cur[i3 + 2]) * 0.05;
      tmp.fromArray(colors, i3);
      tmp.lerp(isGold[i] ? GOLD : BLUE, 0.045);
      if (P.glow > 0) tmp.lerp(WHITE, P.glow * 0.14 * (0.5 + 0.5 * Math.sin(t * 24 + i)));
      tmp.toArray(colors, i3);
    } else {
      const a = t * 0.12 + i * 0.01;
      cur[i3] += (dust[i3] * Math.cos(a * 0.1) - cur[i3]) * 0.008 + Math.sin(t + i) * 0.0008;
      cur[i3 + 1] += (dust[i3 + 1] - cur[i3 + 1]) * 0.008 + Math.cos(t * 0.8 + i) * 0.0008;
      cur[i3 + 2] += (dust[i3 + 2] * Math.cos(a * 0.1) - cur[i3 + 2]) * 0.008;
      tmp.fromArray(colors, i3); tmp.lerp(DIM, 0.05); tmp.toArray(colors, i3);
    }
  }
  geo.getAttribute("position").needsUpdate = true;
  geo.getAttribute("color").needsUpdate = true;

  let m = 0;
  while (m < pairs.length && pairs[m][2] < revealed) m++;
  for (let p = 0; p < m; p++) {
    const [i, j] = pairs[p];
    lPos[p * 6] = cur[i * 3]; lPos[p * 6 + 1] = cur[i * 3 + 1]; lPos[p * 6 + 2] = cur[i * 3 + 2];
    lPos[p * 6 + 3] = cur[j * 3]; lPos[p * 6 + 4] = cur[j * 3 + 1]; lPos[p * 6 + 5] = cur[j * 3 + 2];
    for (let c = 0; c < 2; c++) {
      const col = isGold[c === 0 ? i : j] ? GOLD : BLUE;
      lCol[p * 6 + c * 3] = col.r * 0.5; lCol[p * 6 + c * 3 + 1] = col.g * 0.5; lCol[p * 6 + c * 3 + 2] = col.b * 0.5;
    }
  }
  lineMat.opacity = P.lines;
  lineGeo.setDrawRange(0, m * 2);
  lineGeo.getAttribute("position").needsUpdate = true;
  lineGeo.getAttribute("color").needsUpdate = true;

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

/* ---------- scroll choreography ---------- */
/* master: the human forms as the whole page scrolls */
gsap.to(P, {
  coverage: 0.98, lines: 0.34, rotBoost: 1.15, camZ: 2.35,
  ease: "none",
  scrollTrigger: { trigger: "#story", start: "top top", end: "bottom bottom", scrub: 0.6 },
});
/* warmth: cold space → warm gold as consent approaches */
gsap.to(P, {
  warmth: 1, ease: "none",
  scrollTrigger: {
    trigger: "#consent", start: "top 90%", end: "top 30%", scrub: 0.6,
    onUpdate: () => {
      document.documentElement.style.setProperty("--bg-warm", String(P.warmth * 0.5));
    },
  },
});
/* glow pulse at the consent moment */
ScrollTrigger.create({
  trigger: "#consent .moment",
  start: "top 55%",
  onEnter: () => gsap.fromTo(P, { glow: 1 }, { glow: 0, duration: 2.4, ease: "power2.out" }),
});

/* hero type: split reveal.
   NOTE: SplitText wraps chars in child elements, which breaks the parent's
   background-clip:text gradient (transparent fill, nothing left to clip).
   Re-apply the gradient per character. */
try {
  const split = new SplitText("#hero h1", { type: "chars" });
  split.chars.forEach((c) => {
    c.style.cssText +=
      "background:linear-gradient(135deg,#EDF2F7 30%,#E3B564 100%);" +
      "-webkit-background-clip:text;background-clip:text;" +
      "-webkit-text-fill-color:transparent;display:inline-block;";
  });
  gsap.from(split.chars, {
    opacity: 0, y: 40, rotateX: -50, stagger: 0.035, duration: 1.1, ease: "power3.out", delay: 0.3,
  });
} catch (e) { /* SplitText unavailable — heading stays visible */ }
gsap.from("#hero .sub, #hero .cue", { opacity: 0, y: 18, duration: 1, stagger: 0.15, delay: 1.0, ease: "power2.out" });

/* every content block: rise + fade in on entry */
document.querySelectorAll("[data-rise]").forEach((el) => {
  gsap.from(el, {
    opacity: 0, y: 56, duration: 1.05, ease: "power3.out",
    scrollTrigger: { trigger: el, start: "top 82%" },
  });
});
/* layered parallax: each depth scrolls at its own speed */
document.querySelectorAll("[data-depth]").forEach((el) => {
  const d = parseFloat(el.dataset.depth);
  gsap.to(el, {
    y: () => -d * 120, ease: "none",
    scrollTrigger: { trigger: el.closest("section"), start: "top bottom", end: "bottom top", scrub: 0.5 },
  });
});
/* noticed cards: staggered entry */
gsap.from("#noticing .card", {
  opacity: 0, y: 70, stagger: 0.16, duration: 1, ease: "power3.out",
  scrollTrigger: { trigger: "#noticing .cards", start: "top 78%" },
});
