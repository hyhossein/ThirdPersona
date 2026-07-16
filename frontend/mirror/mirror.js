/* ============================================================
   THIRDPERSONA — THE MIRROR (face-scan prototype)

   The camera sees you. You become the figure: a living particle
   field sampled from your own face, in real time, on-device.
   When you move, it moves. When you talk, it talks, because it
   IS you, not a puppet pretending to be. Nothing is uploaded.
   No face ever leaves this page.

   The reflection law still holds: it speaks only what you gave
   it, as a golden wave through your own image.
   ============================================================ */

import * as THREE from "three";
import { gsap } from "gsap";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- mood + reflections (on-device) ---------- */
const MOODS = {
  tension: ["stressed", "anxious", "tense", "worried", "afraid", "scared", "angry", "frustrated", "restless", "overwhelmed"],
  weight: ["tired", "exhausted", "drained", "heavy", "empty", "numb", "alone", "lonely", "lost", "sad"],
  warmth: ["love", "grateful", "happy", "hope", "warm", "proud", "excited", "alive", "peace", "calm", "free"],
  longing: ["wish", "want", "miss", "dream", "someday", "if only", "used to", "wonder"],
};
function detectMood(text) {
  const l = " " + text.toLowerCase() + " ";
  const scores = {};
  for (const [m, words] of Object.entries(MOODS)) scores[m] = words.reduce((a, w) => a + (l.includes(w) ? 1 : 0), 0);
  const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : null;
}
const REFLECT = {
  tension: "We noticed tension in what you gave us. Look at yourself holding it.",
  weight: "We noticed a heaviness in your words. It is part of the face you see now.",
  warmth: "We noticed warmth in what you said. It suits you.",
  longing: "We noticed a reaching in your words. It is written on you.",
  plain: "We noticed you told the truth. This is what that looks like.",
};

/* ---------- particle mirror ---------- */
const GRID_W = 128, GRID_H = 96;
const NP = GRID_W * GRID_H;

const canvas = document.getElementById("gl");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.1, 50);
camera.position.set(0, 0, 3.1);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
renderer.setSize(innerWidth, innerHeight);

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

const positions = new Float32Array(NP * 3);
const colors = new Float32Array(NP * 3);
const ASPECT = GRID_W / GRID_H;
const SCALE = 2.2;
for (let r = 0; r < GRID_H; r++) {
  for (let c = 0; c < GRID_W; c++) {
    const i = r * GRID_W + c;
    positions[i * 3] = ((c / GRID_W) - 0.5) * SCALE * ASPECT * 0.75;
    positions[i * 3 + 1] = (0.5 - (r / GRID_H)) * SCALE;
    positions[i * 3 + 2] = 0;
    colors[i * 3] = colors[i * 3 + 1] = colors[i * 3 + 2] = 0;
  }
}
const geo = new THREE.BufferGeometry();
geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
const mat = new THREE.PointsMaterial({
  size: 0.026, vertexColors: true, map: makeSprite(), transparent: true,
  opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
});
const points = new THREE.Points(geo, mat);
scene.add(points);

/* brand duotone: shadows go slate blue, light goes gold */
const C_DARK = { r: 0.06, g: 0.08, b: 0.14 };
const C_MID = { r: 0.35, g: 0.42, b: 0.75 };   // #8D9EF0-ish
const C_HI = { r: 0.89, g: 0.71, b: 0.39 };    // #E3B564-ish

const S = {
  vivid: 0.55,     // how much of "you" shows through; honesty raises it
  wave: -1,        // reflection shimmer position (-1 = off)
  depth: 0.42,     // luminance relief
};

/* webcam pipeline */
const video = document.createElement("video");
video.playsInline = true; video.muted = true;
const grab = document.createElement("canvas");
grab.width = GRID_W; grab.height = GRID_H;
const gctx = grab.getContext("2d", { willReadFrequently: true });
let camOn = false;

async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
    });
    video.srcObject = stream;
    await video.play();
    camOn = true;
    document.getElementById("scan").style.display = "none";
    document.getElementById("voiceui").style.display = "flex";
    setPrompt("Say one true thing.");
    gsap.from(S, { vivid: 0, duration: 2.2, ease: "power2.out" });
  } catch (e) {
    setPrompt("The camera stayed closed. That is allowed here.", true);
  }
}
document.getElementById("scan").addEventListener("click", startCamera);

let t = 0, frameCount = 0;
function frame() {
  t += 0.008;
  frameCount++;

  if (camOn && video.readyState >= 2 && frameCount % 2 === 0) {
    /* center-crop the video into the grid, mirrored */
    const vw = video.videoWidth, vh = video.videoHeight;
    const side = Math.min(vw, vh * ASPECT);
    gctx.save();
    gctx.scale(-1, 1);
    gctx.drawImage(video, (vw - side) / 2, (vh - side / ASPECT) / 2, side, side / ASPECT, -GRID_W, 0, GRID_W, GRID_H);
    gctx.restore();
    const px = gctx.getImageData(0, 0, GRID_W, GRID_H).data;

    for (let i = 0; i < NP; i++) {
      const R = px[i * 4] / 255, G = px[i * 4 + 1] / 255, B = px[i * 4 + 2] / 255;
      const lum = 0.2126 * R + 0.7152 * G + 0.0722 * B;

      /* depth relief: brighter pixels come toward you, with a breath */
      positions[i * 3 + 2] = lum * S.depth + Math.sin(t * 1.1 + i * 0.02) * 0.006;

      /* duotone mapping, vividness controls how much appears */
      const v = lum * S.vivid;
      let r, g, b;
      if (v < 0.25) {
        const k = v / 0.25;
        r = C_DARK.r * k; g = C_DARK.g * k; b = C_DARK.b * k;
      } else if (v < 0.6) {
        const k = (v - 0.25) / 0.35;
        r = C_DARK.r + (C_MID.r - C_DARK.r) * k;
        g = C_DARK.g + (C_MID.g - C_DARK.g) * k;
        b = C_DARK.b + (C_MID.b - C_DARK.b) * k;
      } else {
        const k = Math.min(1, (v - 0.6) / 0.4);
        r = C_MID.r + (C_HI.r - C_MID.r) * k;
        g = C_MID.g + (C_HI.g - C_MID.g) * k;
        b = C_MID.b + (C_HI.b - C_MID.b) * k;
      }

      /* the reflection wave: a band of gold light passing down your face */
      if (S.wave >= 0) {
        const rowY = 1 - (Math.floor(i / GRID_W) / GRID_H);
        const d = Math.abs(rowY - S.wave);
        if (d < 0.09) {
          const k = 1 - d / 0.09;
          r += C_HI.r * k * 0.8; g += C_HI.g * k * 0.8; b += C_HI.b * k * 0.8;
        }
      }
      colors[i * 3] = r; colors[i * 3 + 1] = g; colors[i * 3 + 2] = b;
    }
    geo.getAttribute("position").needsUpdate = true;
    geo.getAttribute("color").needsUpdate = true;
  }

  points.rotation.y = Math.sin(t * 0.18) * 0.05;
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

/* ---------- voice: same soul loop, pointed at your own image ---------- */
const prompt_ = document.getElementById("prompt");
const captionEl = document.getElementById("caption");
const micBtn = document.getElementById("mic");
const utterances = [];
let state = "idle";
function setPrompt(text, dim) { prompt_.textContent = text; prompt_.style.opacity = dim ? 0.55 : 1; }

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
micBtn.addEventListener("click", () => {
  if (state !== "idle") return;
  if (!SR) { setPrompt("This browser cannot hear. Chrome or Safari can.", true); return; }
  state = "listening";
  micBtn.classList.add("live");
  setPrompt("It is listening.", true);
  const rec = new SR();
  rec.lang = navigator.language || "en-US";
  rec.interimResults = true;
  let finalText = "";
  rec.onresult = (ev) => {
    let interim = "";
    for (const r of ev.results) { if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript; }
    captionEl.textContent = interim || finalText;
    captionEl.style.opacity = "0.5";
  };
  rec.onerror = () => { state = "idle"; micBtn.classList.remove("live"); setPrompt("Say one true thing."); };
  rec.onend = () => {
    micBtn.classList.remove("live");
    state = "idle";
    if (finalText.trim()) absorb(finalText.trim());
    else setPrompt("Say one true thing.");
  };
  try { rec.start(); } catch (e) { state = "idle"; micBtn.classList.remove("live"); }
});

function absorb(text) {
  utterances.push(text);
  captionEl.textContent = "";
  gsap.to(S, { vivid: Math.min(1.1, S.vivid + 0.14), duration: 1.6, ease: "power2.out" });
  if (utterances.length >= 2) reflect();
  else setPrompt("Say another. Watch yourself become clearer.", true);
}

function reflect() {
  state = "reflecting";
  const line = REFLECT[detectMood(utterances.join(" ")) || "plain"];
  setPrompt("", true);
  captionEl.style.opacity = "1";
  captionEl.textContent = "";
  let i = 0;
  const type = setInterval(() => {
    i += 1;
    captionEl.textContent = line.slice(0, i);
    if (i >= line.length) clearInterval(type);
  }, 26);

  /* the golden wave passes through your image as it speaks */
  gsap.fromTo(S, { wave: 1.05 }, { wave: -0.1, duration: 3.2, ease: "power1.inOut", onComplete: () => { S.wave = -1; } });

  if ("speechSynthesis" in window && !REDUCED) {
    const u = new SpeechSynthesisUtterance(line);
    u.rate = 0.9; u.pitch = 0.85; u.volume = 0.9;
    const pick = speechSynthesis.getVoices().find((v) => /en/i.test(v.lang) && /female|samantha|serena|aria|libby/i.test(v.name));
    if (pick) u.voice = pick;
    speechSynthesis.speak(u);
  }
  setTimeout(() => { state = "idle"; setPrompt("Say one true thing.", false); }, line.length * 26 + 1400);
}

window.__tp = { absorb, reflect, S, startCamera };
