/* ============================================================
   THIRDPERSONA — "Give it soul" (landing v2)

   One screen. A human of dust, alive but soulless: it breathes,
   its heart barely beats, it waits. You speak one true thing.
   Your voice agitates its dust. Your words dissolve into its
   chest and become part of it. After it has enough of you,
   it speaks back ONCE: a reflection built only from what you
   gave it. It never greets. It never asks. It has no words
   of its own. That is the law that keeps it from being a chatbot.
   ============================================================ */

import * as THREE from "three";
import { gsap } from "gsap";

/* ---------- environment ---------- */
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const MOBILE = innerWidth < 640;
const store = (() => {
  try { localStorage.setItem("__t", "1"); localStorage.removeItem("__t"); return localStorage; }
  catch (e) { return null; }
})();

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

/* ---------- mood (on-device, nothing leaves the page) ---------- */
const MOODS = {
  tension: ["stressed", "anxious", "tense", "worried", "afraid", "scared", "angry", "frustrated", "restless", "overwhelmed"],
  weight: ["tired", "exhausted", "drained", "heavy", "empty", "numb", "alone", "lonely", "lost", "sad"],
  warmth: ["love", "grateful", "happy", "hope", "warm", "proud", "excited", "alive", "peace", "calm", "free"],
  longing: ["wish", "want", "miss", "dream", "someday", "if only", "used to", "wonder"],
};
function detectMood(text) {
  const l = " " + text.toLowerCase() + " ";
  const scores = {};
  for (const [m, words] of Object.entries(MOODS)) {
    scores[m] = words.reduce((a, w) => a + (l.includes(w) ? 1 : 0), 0);
  }
  const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : null;
}
const REFLECT = {
  tension: "We noticed tension in what you gave us. It is held now, not judged.",
  weight: "We noticed a heaviness in your words. It is part of you here, and it is safe.",
  warmth: "We noticed warmth in what you said. That is part of your shape now.",
  longing: "We noticed a reaching in your words, toward something not yet here. We kept it.",
  plain: "We noticed you told the truth. That is all we are made of.",
};

/* ---------- three.js: the soulless human ---------- */
const canvas = document.getElementById("gl");
let webgl = true;
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch (e) {
  webgl = false;
  document.getElementById("nogl").style.display = "flex";
}

const P = {
  coverage: 0.06,
  glow: 0,
  agitate: 0,     // your voice shakes its dust
  breath: 1,      // breaths per ~6s, deepens as it gains soul
  heart: 0.25,    // heartbeat strength
  listenTilt: 0,  // it leans in when you speak
};
if (store) {
  const saved = parseFloat(store.getItem("tp_coverage"));
  if (!isNaN(saved)) P.coverage = Math.min(0.85, Math.max(0.06, saved));
}

let scene, camera, group, geo, colors, cur, dust, targets, isGold, N, heartMat, lineMat, lineGeo, lPos, lCol, pairs, stars;
if (webgl) {
  N = MOBILE ? 1300 : 2400;
  const SEED = 99173;
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.1, 100);
  camera.position.set(0, 0.22, 2.55);
  renderer.setPixelRatio(Math.min(devicePixelRatio, MOBILE ? 1.5 : 1.75));
  renderer.setSize(innerWidth, innerHeight);

  const sprite = makeSprite();
  group = new THREE.Group();
  scene.add(group);

  targets = generateBustPoints(N, SEED);
  dust = new Float32Array(N * 3);
  cur = new Float32Array(N * 3);
  const rng = seededRandom(SEED + 1);
  for (let i = 0; i < N; i++) {
    const r = 1.9 + rng() * 1.7;
    const u = rng() * 2 - 1, th = rng() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    dust[i * 3] = sq * Math.cos(th) * r;
    dust[i * 3 + 1] = u * r * 0.7 + 0.1;
    dust[i * 3 + 2] = sq * Math.sin(th) * r;
    cur.set(dust.subarray(i * 3, i * 3 + 3), i * 3);
  }
  colors = new Float32Array(N * 3);
  const DIM = new THREE.Color("#232B3E");
  isGold = new Uint8Array(N);
  for (let i = 0; i < N; i++) { isGold[i] = rng() > 0.62 ? 1 : 0; DIM.toArray(colors, i * 3); }

  geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(cur, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  group.add(new THREE.Points(geo, new THREE.PointsMaterial({
    size: 0.032, vertexColors: true, map: sprite, transparent: true,
    opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
  })));

  /* the heart: a small cluster in the chest, barely beating until you feed it */
  const NH = 42, hPos = new Float32Array(NH * 3), hrng = seededRandom(SEED + 77);
  for (let i = 0; i < NH; i++) {
    const r = 0.055 * Math.cbrt(hrng());
    const u = hrng() * 2 - 1, th = hrng() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    hPos[i * 3] = sq * Math.cos(th) * r;
    hPos[i * 3 + 1] = u * r + 0.30;
    hPos[i * 3 + 2] = sq * Math.sin(th) * r + 0.08;
  }
  const heartGeo = new THREE.BufferGeometry();
  heartGeo.setAttribute("position", new THREE.BufferAttribute(hPos, 3));
  heartMat = new THREE.PointsMaterial({
    size: 0.05, color: 0xE3B564, map: sprite, transparent: true, opacity: 0.0,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
  });
  group.add(new THREE.Points(heartGeo, heartMat));

  /* starfield */
  const NS = MOBILE ? 400 : 800, sPos = new Float32Array(NS * 3), srng = seededRandom(SEED + 31);
  for (let i = 0; i < NS; i++) {
    const r = 3.4 + srng() * 5.5, u = srng() * 2 - 1, th = srng() * Math.PI * 2;
    const sq = Math.sqrt(1 - u * u);
    sPos[i * 3] = sq * Math.cos(th) * r; sPos[i * 3 + 1] = u * r * 0.6 + 0.1; sPos[i * 3 + 2] = sq * Math.sin(th) * r;
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute("position", new THREE.BufferAttribute(sPos, 3));
  stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    size: 0.016, color: 0x2c3854, map: sprite, transparent: true, opacity: 0.75,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
  }));
  scene.add(stars);

  /* constellation lines */
  pairs = [];
  const cell = new Map();
  for (let i = 0; i < N; i++) {
    const k = `${Math.floor(targets[i * 3] / 0.14)},${Math.floor(targets[i * 3 + 1] / 0.14)},${Math.floor(targets[i * 3 + 2] / 0.14)}`;
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
  lPos = new Float32Array(pairs.length * 6);
  lCol = new Float32Array(pairs.length * 6);
  lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute("position", new THREE.BufferAttribute(lPos, 3));
  lineGeo.setAttribute("color", new THREE.BufferAttribute(lCol, 3));
  lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending });
  group.add(new THREE.LineSegments(lineGeo, lineMat));
}

/* pointer parallax */
let px = 0, py = 0;
addEventListener("pointermove", (e) => {
  px = (e.clientX / innerWidth - 0.5) * 2;
  py = (e.clientY / innerHeight - 0.5) * 2;
});

/* heartbeat curve: lub-dub */
function heartbeat(t, rate) {
  const c = (t * rate) % 1;
  const p1 = Math.exp(-Math.pow((c - 0.12) * 18, 2));
  const p2 = Math.exp(-Math.pow((c - 0.34) * 22, 2)) * 0.6;
  return p1 + p2;
}

let t = 0;
const tmp = new THREE.Color();
const GOLD = new THREE.Color("#E3B564"), BLUE = new THREE.Color("#8D9EF0"), DIMC = new THREE.Color("#232B3E"), WHITE = new THREE.Color("#FFFFFF");
function frame() {
  if (window.__TP_STOP) return; // combined build: app took over
  t += REDUCED ? 0.003 : 0.008;
  if (webgl) {
    const breathe = 1 + Math.sin(t * 0.9 * P.breath) * (REDUCED ? 0.002 : 0.006 + P.coverage * 0.006);
    group.scale.setScalar(breathe);
    group.rotation.y = Math.sin(t * 0.07) * 0.35 + px * 0.06;          // idle drift + slight face-you
    group.rotation.x = P.listenTilt * 0.06;                             // leans in while listening
    stars.rotation.y = t * 0.012;
    camera.position.x += (px * 0.07 - camera.position.x) * 0.03;
    camera.position.y += (0.22 - py * 0.04 - camera.position.y) * 0.03;
    camera.lookAt(0, 0.18, 0);

    const hb = heartbeat(t, 0.45 + P.agitate * 0.5 + P.coverage * 0.25);
    heartMat.opacity = (0.05 + P.heart * 0.5) * (0.35 + hb);
    heartMat.size = 0.045 + hb * 0.02;

    const revealed = Math.floor(N * Math.min(1, Math.max(0, P.coverage)));
    const agit = P.agitate * (REDUCED ? 0.15 : 1);
    for (let i = 0; i < N; i++) {
      const i3 = i * 3;
      if (i < revealed) {
        const shake = agit * 0.012;
        const bx = targets[i3] + Math.sin(t * 1.4 + i) * 0.004 + (Math.random() - 0.5) * shake;
        const by = targets[i3 + 1] + Math.cos(t * 1.2 + i) * 0.004 + (Math.random() - 0.5) * shake;
        const bz = targets[i3 + 2] + Math.sin(t * 1.1 + i * 0.7) * 0.004 + (Math.random() - 0.5) * shake;
        cur[i3] += (bx - cur[i3]) * 0.05;
        cur[i3 + 1] += (by - cur[i3 + 1]) * 0.05;
        cur[i3 + 2] += (bz - cur[i3 + 2]) * 0.05;
        tmp.fromArray(colors, i3);
        tmp.lerp(isGold[i] ? GOLD : BLUE, 0.045);
        if (P.glow > 0) tmp.lerp(WHITE, P.glow * 0.15 * (0.5 + 0.5 * Math.sin(t * 22 + i)));
        tmp.toArray(colors, i3);
      } else {
        const a = t * 0.12 + i * 0.01;
        const drift = 1 + agit * 0.35;
        cur[i3] += (dust[i3] * Math.cos(a * 0.1) - cur[i3]) * 0.008 * drift + Math.sin(t + i) * 0.0008 * drift;
        cur[i3 + 1] += (dust[i3 + 1] - cur[i3 + 1]) * 0.008 * drift + Math.cos(t * 0.8 + i) * 0.0008 * drift;
        cur[i3 + 2] += (dust[i3 + 2] * Math.cos(a * 0.1) - cur[i3 + 2]) * 0.008 * drift;
        tmp.fromArray(colors, i3); tmp.lerp(DIMC, 0.05); tmp.toArray(colors, i3);
      }
    }
    geo.getAttribute("position").needsUpdate = true;
    geo.getAttribute("color").needsUpdate = true;

    let m = 0;
    while (m < pairs.length && pairs[m][2] < revealed) m++;
    for (let p = 0; p < m; p++) {
      const [i, j] = pairs[p];
      // Only draw a line once BOTH endpoints have settled near the body.
      // Points still travelling in from deep dust would otherwise create
      // screen-crossing streaks.
      const di = (cur[i*3]-targets[i*3])**2 + (cur[i*3+1]-targets[i*3+1])**2 + (cur[i*3+2]-targets[i*3+2])**2;
      const dj = (cur[j*3]-targets[j*3])**2 + (cur[j*3+1]-targets[j*3+1])**2 + (cur[j*3+2]-targets[j*3+2])**2;
      if (di > 0.02 || dj > 0.02) {
        lPos[p * 6] = lPos[p * 6 + 3] = cur[i * 3];
        lPos[p * 6 + 1] = lPos[p * 6 + 4] = cur[i * 3 + 1];
        lPos[p * 6 + 2] = lPos[p * 6 + 5] = cur[i * 3 + 2];
        continue;
      }
      lPos[p * 6] = cur[i * 3]; lPos[p * 6 + 1] = cur[i * 3 + 1]; lPos[p * 6 + 2] = cur[i * 3 + 2];
      lPos[p * 6 + 3] = cur[j * 3]; lPos[p * 6 + 4] = cur[j * 3 + 1]; lPos[p * 6 + 5] = cur[j * 3 + 2];
      for (let c = 0; c < 2; c++) {
        const col = isGold[c === 0 ? i : j] ? GOLD : BLUE;
        lCol[p * 6 + c * 3] = col.r * 0.5; lCol[p * 6 + c * 3 + 1] = col.g * 0.5; lCol[p * 6 + c * 3 + 2] = col.b * 0.5;
      }
    }
    lineMat.opacity = 0.08 + P.coverage * 0.26;
    lineGeo.setDrawRange(0, m * 2);
    lineGeo.getAttribute("position").needsUpdate = true;
    lineGeo.getAttribute("color").needsUpdate = true;

    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

addEventListener("resize", () => {
  if (!webgl) return;
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

/* ============================================================
   VOICE — you speak, it absorbs. It answers only with what
   you gave it.
   ============================================================ */
const micBtn = document.getElementById("mic");
const micRing = document.getElementById("micring");
const prompt_ = document.getElementById("prompt");
const percentEl = document.getElementById("percent");
const captionEl = document.getElementById("caption");
const typeToggle = document.getElementById("typetoggle");
const typeWrap = document.getElementById("typewrap");
const typeInput = document.getElementById("typeinput");

const utterances = [];
let state = "idle";  // idle | listening | absorbing | reflecting
let analyser = null, audioCtx = null, micStream = null;

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;

function setPrompt(text, dim) {
  prompt_.textContent = text;
  prompt_.style.opacity = dim ? 0.55 : 1;
}

async function startAudioLevel() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaStreamSource(micStream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    (function level() {
      if (!analyser) return;
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const rms = Math.sqrt(sum / buf.length);
      if (state === "listening") {
        P.agitate += (Math.min(1, rms * 9) - P.agitate) * 0.25;
        micRing.style.transform = `scale(${1 + Math.min(1, rms * 9) * 0.55})`;
        micRing.style.opacity = String(0.35 + Math.min(1, rms * 9) * 0.5);
      }
      requestAnimationFrame(level);
    })();
  } catch (e) { /* no level meter; recognition may still work */ }
}
function stopAudioLevel() {
  if (micStream) { micStream.getTracks().forEach((tr) => tr.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
  analyser = null;
  micRing.style.opacity = "0";
  gsap.to(P, { agitate: 0, duration: 0.8 });
}

function listen() {
  if (state !== "idle") return;
  if (!SR) { showTyping(); return; }
  state = "listening";
  micBtn.classList.add("live");
  setPrompt("It is listening.", true);
  P.listenTilt = 1;
  startAudioLevel();

  rec = new SR();
  rec.lang = navigator.language || "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  let finalText = "";
  rec.onresult = (ev) => {
    let interim = "";
    for (const r of ev.results) {
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    captionEl.textContent = interim || finalText;
    captionEl.style.opacity = "0.5";
  };
  rec.onerror = (ev) => {
    endListen();
    if (ev.error === "not-allowed" || ev.error === "service-not-allowed") showTyping("Your browser kept the microphone. Type instead.");
    else setPrompt("Say one true thing.");
  };
  rec.onend = () => {
    endListen();
    if (finalText.trim()) absorb(finalText.trim());
    else if (state === "idle") setPrompt("Say one true thing.");
  };
  try { rec.start(); } catch (e) { endListen(); showTyping(); }
}
function endListen() {
  state = "idle";
  micBtn.classList.remove("live");
  P.listenTilt = 0;
  stopAudioLevel();
}

function showTyping(msg) {
  typeWrap.style.display = "flex";
  micBtn.style.display = "none";
  if (msg) setPrompt(msg, true);
  typeInput.focus();
}
typeToggle.addEventListener("click", (e) => { e.preventDefault(); showTyping(); });
typeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && typeInput.value.trim()) {
    absorb(typeInput.value.trim());
    typeInput.value = "";
  }
});
micBtn.addEventListener("click", listen);

/* words dissolve into the chest */
function absorb(text) {
  state = "absorbing";
  utterances.push(text);
  captionEl.textContent = "";

  const words = text.split(/\s+/).slice(0, 14);
  const cx = innerWidth / 2, cy = innerHeight * 0.42;
  words.forEach((w, i) => {
    const el = document.createElement("span");
    el.className = "word";
    el.textContent = w;
    el.style.left = `${cx + (Math.random() - 0.5) * 300}px`;
    el.style.top = `${innerHeight * 0.72 + (Math.random() - 0.5) * 40}px`;
    document.body.appendChild(el);
    gsap.to(el, {
      left: cx + (Math.random() - 0.5) * 30,
      top: cy + (Math.random() - 0.5) * 30,
      opacity: 0, scale: 0.4, duration: REDUCED ? 0.6 : 1.3 + Math.random() * 0.5,
      delay: i * 0.07, ease: "power2.in",
      onComplete: () => el.remove(),
    });
  });

  const gain = Math.min(0.05, 0.012 + words.length * 0.0022);
  gsap.to(P, { coverage: Math.min(0.9, P.coverage + gain), duration: 1.6, ease: "power2.out", delay: 0.5 });
  gsap.fromTo(P, { glow: 0.9 }, { glow: 0, duration: 2.2, ease: "power2.out", delay: 0.6 });
  gsap.to(P, { heart: Math.min(1, P.heart + 0.2), breath: Math.min(1.6, P.breath + 0.08), duration: 1.5 });
  if (store) store.setItem("tp_coverage", String(Math.min(0.9, P.coverage + gain)));

  setTimeout(() => {
    const pct = Math.round(Math.min(0.9, P.coverage) * 100);
    percentEl.textContent = `That was ${pct}% of you.`;
    gsap.fromTo(percentEl, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.8 });
    state = "idle";
    if (utterances.length >= 2) reflect();
    else setPrompt("Say another.", true);
  }, REDUCED ? 700 : 1800);
}

/* it speaks back only what you gave it */
function reflect() {
  state = "reflecting";
  const all = utterances.join(" ");
  const mood = detectMood(all);
  const line = REFLECT[mood || "plain"];

  setPrompt("", true);
  captionEl.style.opacity = "1";
  captionEl.textContent = "";
  let i = 0;
  const type = setInterval(() => {
    i += 1;
    captionEl.textContent = line.slice(0, i);
    if (i >= line.length) clearInterval(type);
  }, 26);

  if ("speechSynthesis" in window && !REDUCED) {
    const u = new SpeechSynthesisUtterance(line);
    u.rate = 0.9; u.pitch = 0.85; u.volume = 0.9;
    const pick = speechSynthesis.getVoices().find((v) => /en/i.test(v.lang) && /female|samantha|serena|aria|libby/i.test(v.name));
    if (pick) u.voice = pick;
    u.onboundary = () => gsap.fromTo(P, { glow: 0.5 }, { glow: 0.1, duration: 0.3 });
    u.onend = () => gsap.to(P, { glow: 0, duration: 1 });
    speechSynthesis.speak(u);
  }

  setTimeout(() => {
    state = "idle";
    setPrompt("Say one true thing.", false);
    document.getElementById("cta").classList.add("show");
  }, line.length * 26 + 1200);
}

/* debug hook for automated verification (no mic in headless browsers) */
window.__tp = { absorb, reflect, P, utterances };

/* first paint */
setPrompt("Say one true thing.");
if (P.coverage > 0.08) {
  percentEl.textContent = `${Math.round(P.coverage * 100)}% of you is already here. It kept your words.`;
  percentEl.style.opacity = "1";
}
