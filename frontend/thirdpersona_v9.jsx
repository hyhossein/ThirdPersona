import { useState, useEffect, useRef, useMemo } from "react";
import * as THREE from "three";

// ============================================================
// THIRDPERSONA v9 — "The Unfinished Human", refined
//
// Visual system: deep-space glass, gold/periwinkle signature,
// serif display voice, luminous point-cloud bust with additive
// glow and a starfield of everything unwritten.
//
// Product-truth upgrade over v8: patterns are HYPOTHESES in
// "we noticed…" language. Nothing becomes part of you without
// an explicit "That's me." Rejections teach the system and are
// never re-surfaced. Rejection rate >40% pauses discovery
// (the circuit breaker) — the demo behaves like the real backend.
//
// Live mode: point it at the FastAPI backend (gear icon) and it
// reads/writes real entries & hypotheses via /entries, /patterns.
// ============================================================

// ---------- design tokens ----------
const T = {
  bg: "#05070C",
  surface: "#0E1219",
  glass: "rgba(14,18,25,0.72)",
  well: "#07090E",
  border: "rgba(123,142,200,0.14)",
  borderSoft: "rgba(123,142,200,0.08)",
  ink: "#EDF2F7",
  ink2: "#9AA6B5",
  ink3: "#5A6472",
  ink4: "#39414D",
  gold: "#C9A96E",
  goldBright: "#E3B564", // data marks (validated on dark surface)
  blue: "#7B8EC8",
  blueBright: "#8D9EF0",
  green: "#54C48E",
  red: "#F07E70",
  serif: "Georgia, 'Iowan Old Style', 'Times New Roman', serif",
  sans: "'Inter', -apple-system, system-ui, sans-serif",
};
const CAT_COL = { relational: T.blueBright, self: T.green, conflict: T.red, social: T.goldBright, emotional: T.blueBright, energy: T.green, values: T.goldBright, growth: T.green, intellectual: T.blueBright };

// ---------- deterministic helpers ----------
function hashText(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  return Math.abs(h) || 1;
}
function seededRandom(seed) {
  let s = seed;
  return () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
}
function glyphParams(text) {
  const h = hashText(text);
  const rng = seededRandom(h);
  return {
    symmetry: Math.floor(rng() * 5) + 5, rings: Math.floor(rng() * 2) + 3,
    hue1: Math.floor(rng() * 360), hue2: (Math.floor(rng() * 360) + 120) % 360,
    wobble: 0.25 + rng() * 0.5, rot: rng() * Math.PI * 2, seed: h,
  };
}
function glyphTargets(params, cx, cy, scale, count) {
  const rng = seededRandom(params.seed + 7);
  const targets = [];
  for (let i = 0; i < count; i++) {
    const ring = i % params.rings;
    const baseR = (0.28 + ring * 0.22) * scale;
    const t = (i / count) * Math.PI * 2 * params.symmetry + params.rot;
    const petal = Math.sin(t) * params.wobble * baseR * 0.6;
    const angle = (i / count) * Math.PI * 2 + params.rot + ring * 0.35;
    targets.push({ x: cx + Math.cos(angle) * (baseR + petal + (rng() - 0.5) * 4), y: cy + Math.sin(angle) * (baseR + petal + (rng() - 0.5) * 4), ring });
  }
  return targets;
}

// ---------- mood ----------
const MOOD_WORDS = {
  energy: { high: ["excited","energized","alive","motivated","inspired","driven","charged"], low: ["tired","exhausted","drained","depleted","heavy","burnt","overwhelmed"] },
  openness: { high: ["connected","open","vulnerable","shared","close","honest","warm"], low: ["distant","withdrawn","closed","alone","isolated","guarded","numb","disconnected"] },
  tension: { high: ["stressed","anxious","tense","worried","frustrated","angry","restless"], low: ["calm","peaceful","relaxed","centered","still","serene","grounded"] },
};
function detectMood(text) {
  const l = text.toLowerCase(); const s = {};
  for (const [dim, poles] of Object.entries(MOOD_WORDS)) {
    let v = 50;
    poles.high.forEach((w) => { if (l.includes(w)) v += 15; });
    poles.low.forEach((w) => { if (l.includes(w)) v -= 15; });
    s[dim] = Math.max(5, Math.min(95, v));
  }
  return s;
}

// ---------- domains ----------
const DOMAINS = [
  { id: "relationships", label: "Relationships", kw: ["friend","love","partner","family","together","trust","care"] },
  { id: "conflict", label: "Conflict", kw: ["argue","disagree","fight","tension","frustrated","angry","compromise"] },
  { id: "energy", label: "Energy", kw: ["tired","rest","sleep","energized","exhaust","recharge","drain"] },
  { id: "values", label: "Values", kw: ["believe","value","matter","important","meaning","purpose"] },
  { id: "growth", label: "Growth", kw: ["learn","grow","change","improve","realize","discover"] },
  { id: "social", label: "Social", kw: ["group","party","crowd","dinner","gather","social","people"] },
  { id: "intellectual", label: "Mind", kw: ["read","think","idea","philosophy","study","theory"] },
  { id: "emotional", label: "Emotions", kw: ["feel","emotion","mood","happy","sad","joy","anxious"] },
];
function getCoverage(entries) {
  const c = {};
  DOMAINS.forEach((d) => {
    let hits = 0;
    entries.forEach((e) => { if (d.kw.some((k) => e.text.toLowerCase().includes(k))) hits++; });
    c[d.id] = Math.min(100, Math.round((hits / Math.max(entries.length, 1)) * 100 + hits * 12));
  });
  return c;
}
const GAP_PROMPTS = {
  relationships: "Who showed up for you recently?",
  conflict: "When did you last disagree with someone you care about?",
  energy: "What drained you this week? What recharged you?",
  values: "What felt meaningful today? What felt hollow?",
  growth: "What did you learn about yourself recently?",
  social: "How did you feel the last time you were in a group?",
  intellectual: "What idea won't leave you alone?",
  emotional: "Right now, without filtering: what are you actually feeling?",
};

// ---------- seed data ----------
const ENTRIES0 = [
  { id: 1, text: "Had a deep conversation with Tim about his career doubts. I noticed I kept trying to fix it instead of just listening.", people: ["Tim"], date: "2026-06-28", mood: { energy: 45, openness: 65, tension: 40 } },
  { id: 2, text: "Maria and I had a small argument about weekend plans. She wanted spontaneity, I wanted structure. We compromised but I felt unseen.", people: ["Maria"], date: "2026-07-01", mood: { energy: 35, openness: 30, tension: 70 } },
  { id: 3, text: "Roni called to vent. I was exhausted but stayed on for an hour. Felt good to be there even when drained.", people: ["Roni"], date: "2026-07-05", mood: { energy: 20, openness: 60, tension: 30 } },
  { id: 4, text: "Group dinner. Everyone laughing but I felt distant. Maybe overstretched.", people: ["Tim","Roni","Maria","Chris"], date: "2026-07-08", mood: { energy: 30, openness: 25, tension: 55 } },
  { id: 5, text: "Read Rumi for two hours in the park. Felt centered and peaceful for the first time this week.", people: [], date: "2026-07-10", mood: { energy: 70, openness: 80, tension: 10 } },
];

// Hypotheses in the product's real language and lifecycle.
// status: 'hypothesis' (awaiting your yes) | 'active' (you confirmed) | 'rejected'
const PATTERNS0 = [
  { id: "p1", status: "hypothesis", insight: "We noticed that when someone shares vulnerability with you, you seem to move toward solutions before the feeling has finished being said.", category: "relational", evidence: [1, 3], spreadDays: 7, firstSeen: "2026-07-06" },
  { id: "p2", status: "hypothesis", insight: "We noticed a possible pattern of feeling distant in groups of four or more — even when you enjoy each person one-on-one.", category: "social", evidence: [4], spreadDays: 0, firstSeen: "2026-07-09" },
  { id: "p3", status: "hypothesis", insight: "We noticed that in conflict, when you feel unseen, you tend to accommodate rather than name the unmet need — and the feeling resurfaces later.", category: "conflict", evidence: [2], spreadDays: 0, firstSeen: "2026-07-02" },
  { id: "p4", status: "active", insight: "We noticed that solitary, contemplative time consistently restores you — and that you rarely plan for it until you're already depleted.", category: "self", evidence: [5], spreadDays: 12, firstSeen: "2026-06-30", confirmedOn: "2026-07-11" },
  { id: "p5", status: "active", insight: "We noticed your giving may be asymmetric: you show up for others when you're depleted, but you don't signal depletion to anyone.", category: "relational", evidence: [3, 4], spreadDays: 3, firstSeen: "2026-07-09", confirmedOn: "2026-07-12" },
];

const CIRCLE0 = [
  { id: "maria", name: "Maria", joined: true, glyphSeed: "maria-spontaneity-warmth-art", resonance: 0.74 },
  { id: "tim", name: "Tim", joined: false },
  { id: "roni", name: "Roni", joined: false },
  { id: "chris", name: "Chris", joined: false },
];
const CIRCLE_PATTERNS = [
  { id: "cp1", locked: false, insight: "You and Maria both withdraw when you feel unappreciated, but you each read the other's withdrawal as disinterest. Two identical patterns, misread in both directions.", people: ["You", "Maria"] },
  { id: "cp2", locked: false, insight: "Your conflict styles are inverted: you accommodate and feel unseen, she escalates and feels unheard. Neither of you names the underlying need in the moment.", people: ["You", "Maria"] },
  { id: "cp3", locked: true, requires: ["tim"], teaser: "A shared pattern between you and Tim around how you both handle career uncertainty...", people: ["You", "Tim"] },
  { id: "cp4", locked: true, requires: ["roni"], teaser: "Something about the way you and Roni trade emotional labor, visible only from both sides...", people: ["You", "Roni"] },
  { id: "cp5", locked: true, requires: ["tim","roni","chris"], teaser: "A group dynamic across your whole circle that explains the distance you felt at dinner on July 8...", people: ["You","Tim","Roni","Chris"] },
];
const DIALOGUE_SUGGESTIONS = [
  "Is Maria still upset about the weekend plans argument?",
  "What does Maria need from me that she hasn't said?",
  "How does Maria experience my problem-solving habit?",
];
const DIALOGUE_RESPONSES = {
  0: { a: "Not upset in the way you might fear. Her pattern after conflicts like July 1 shows quick emotional recovery but slow trust recalibration. The argument itself is resolved for her. What lingers is a question underneath it: whether spontaneity will always require negotiation with you. She hasn't said this because her pattern is to protect the relationship from what she considers 'small' concerns until they accumulate.", note: "Maria consented to share conflict-domain patterns with you. She can see this question was asked." },
  1: { a: "Her entries show a recurring theme: she experiences your structure as care but also as a container she has to fit into. What she hasn't articulated, possibly even to herself, is that she wants to be the one who plans something for you occasionally. Her giving pattern is spontaneity-based, and your planning leaves little room for her form of giving to land.", note: "This draws on patterns Maria explicitly shared at 'deep' scope. She can see this question was asked." },
  2: { a: "Mixed, and more gently than you'd guess. When she shares practical problems, your fixing lands as competence and she values it. When she shares feelings, your fixing registers as a subject change. Her pattern is to stop sharing feelings mid-conversation when this happens, which you may have noticed as her 'trailing off.'", note: "Maria consented to share relational patterns with you. She can see this question was asked." },
};
const CONTEXTS = {
  dating: { label: "Dating", icon: "♡", desc: "How you show up in closeness", title: "How they handle closeness", insights: ["Shows loyalty through action. Will give their last energy to someone they care about.","Accommodates in conflict rather than naming the need. The real feeling surfaces later.","Needs focused one-on-one attention. Groups create distance.","Recharges through solitary intellectual activity. Respecting this transforms the relationship."] },
  professional: { label: "Professional", icon: "◆", desc: "How you operate at work", title: "Working with this person", insights: ["Strong fixer instinct. Moves to solutions immediately, sometimes skipping the listening phase.","Performs best with depth and focus. Context-switching reduces output quality.","Gives asymmetrically. Will overextend without signaling capacity limits.","Meaning-driven. Tasks connected to purpose get significantly more investment."] },
  social: { label: "Friends", icon: "◎", desc: "What your circle should know", title: "Understanding this person", insights: ["If they seem distant in a group, it's not disinterest. They need depth.","When they fix instead of listen, redirect gently. It's care misrouted.","They won't tell you when they're empty. Check on them."] },
  creator: { label: "Creator", icon: "✧", desc: "Authentic brand alignment", title: "Authentic alignment profile", insights: ["Core: depth, meaning, genuine connection. Performative content conflicts with identity.","Builds community through individual resonance, not broadcast energy.","High fit: philosophy, education, self-development. Low fit: hype-driven campaigns."] },
};

// ============================================================
// THE HUMAN MESH — luminous point-cloud bust (three.js)
// ============================================================
function makeSpriteTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.55)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const tex = new THREE.CanvasTexture(c);
  return tex;
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
      // faint brow + nose suggestion
      if (z > 0.24 && y > 0.55 && y < 0.68) z += 0.015;
      if (z > 0.28 && Math.abs(x) < 0.05 && y > 0.45 && y < 0.58) z += 0.03;
    } else if (region < 0.68) {
      const theta = rng() * Math.PI * 2;
      y = 0.06 + rng() * 0.18;
      const r = 0.125 + (rng() - 0.5) * 0.015;
      x = Math.cos(theta) * r;
      z = Math.sin(theta) * r * 0.9;
    } else {
      const t = rng();
      y = 0.06 - t * 0.56;
      const flare = 0.14 + Math.pow(t, 0.65) * 0.6;
      const theta = rng() * Math.PI * 2;
      x = Math.cos(theta) * flare * 1.25;
      z = Math.sin(theta) * flare * 0.55;
    }
    pts[i * 3] = x + (rng() - 0.5) * 0.012;
    pts[i * 3 + 1] = y + (rng() - 0.5) * 0.012;
    pts[i * 3 + 2] = z + (rng() - 0.5) * 0.012;
  }
  return pts;
}

function HumanMesh({ coverage, height = 380, caption = true, pulse = 0 }) {
  const mountRef = useRef(null);
  const covRef = useRef(coverage);
  const pulseRef = useRef({ n: pulse, until: 0 });
  covRef.current = coverage;
  useEffect(() => {
    if (pulse > pulseRef.current.n) pulseRef.current = { n: pulse, until: performance.now() + 2400 };
  }, [pulse]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const W = mount.clientWidth, H = height;
    const N = 1800, NSTAR = 650, SEED = 99173;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, W / H, 0.1, 100);
    camera.position.set(0, 0.25, 2.6);
    camera.lookAt(0, 0.15, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    mount.appendChild(renderer.domElement);

    const sprite = makeSpriteTexture();
    const group = new THREE.Group();
    scene.add(group);

    // --- distant starfield: everything unwritten ---
    const starPos = new Float32Array(NSTAR * 3);
    const srng = seededRandom(SEED + 31);
    for (let i = 0; i < NSTAR; i++) {
      const r = 3.2 + srng() * 4.5;
      const u = srng() * 2 - 1, th = srng() * Math.PI * 2;
      const sq = Math.sqrt(1 - u * u);
      starPos[i * 3] = sq * Math.cos(th) * r;
      starPos[i * 3 + 1] = u * r * 0.6 + 0.1;
      starPos[i * 3 + 2] = sq * Math.sin(th) * r;
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({ size: 0.016, color: 0x2a3550, map: sprite, transparent: true, opacity: 0.7, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
    scene.add(new THREE.Points(starGeo, starMat));

    // --- the bust ---
    const targets = generateBustPoints(N, SEED);
    const dust = new Float32Array(N * 3);
    const cur = new Float32Array(N * 3);
    const rng = seededRandom(SEED + 1);
    for (let i = 0; i < N; i++) {
      const r = 1.8 + rng() * 1.6;
      const u = rng() * 2 - 1, th = rng() * Math.PI * 2;
      const sq = Math.sqrt(1 - u * u);
      dust[i * 3] = sq * Math.cos(th) * r;
      dust[i * 3 + 1] = u * r * 0.7 + 0.1;
      dust[i * 3 + 2] = sq * Math.sin(th) * r;
      cur[i * 3] = dust[i * 3]; cur[i * 3 + 1] = dust[i * 3 + 1]; cur[i * 3 + 2] = dust[i * 3 + 2];
    }

    const colors = new Float32Array(N * 3);
    const gold = new THREE.Color("#E3B564"), blue = new THREE.Color("#8D9EF0"), dim = new THREE.Color("#242C3D");
    const isGold = new Uint8Array(N);
    for (let i = 0; i < N; i++) {
      isGold[i] = rng() > 0.62 ? 1 : 0;
      dim.toArray(colors, i * 3);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(cur, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.PointsMaterial({ size: 0.03, vertexColors: true, map: sprite, transparent: true, opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
    group.add(new THREE.Points(geo, mat));

    // wireframe segments between near target-neighbors
    const pairs = [];
    const cell = new Map();
    for (let i = 0; i < N; i++) {
      const k = `${Math.floor(targets[i*3] / 0.14)},${Math.floor(targets[i*3+1] / 0.14)},${Math.floor(targets[i*3+2] / 0.14)}`;
      if (!cell.has(k)) cell.set(k, []);
      cell.get(k).push(i);
    }
    for (let i = 0; i < N && pairs.length < 2600; i++) {
      const x = targets[i*3], y = targets[i*3+1], z = targets[i*3+2];
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
        const k = `${Math.floor(x/0.14)+dx},${Math.floor(y/0.14)+dy},${Math.floor(z/0.14)+dz}`;
        const bucket = cell.get(k);
        if (!bucket) continue;
        for (const j of bucket) {
          if (j <= i) continue;
          const ddx = targets[j*3]-x, ddy = targets[j*3+1]-y, ddz = targets[j*3+2]-z;
          if (ddx*ddx + ddy*ddy + ddz*ddz < 0.0121) pairs.push([i, j, Math.max(i, j)]);
        }
      }
    }
    pairs.sort((a, b) => a[2] - b[2]);
    const linePos = new Float32Array(pairs.length * 6);
    const lineCol = new Float32Array(pairs.length * 6);
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
    lineGeo.setAttribute("color", new THREE.BufferAttribute(lineCol, 3));
    const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending });
    group.add(new THREE.LineSegments(lineGeo, lineMat));

    // drag to rotate + gentle pointer parallax
    let dragging = false, lastX = 0, rotY = 0, rotVel = 0.0022, px = 0, py = 0;
    const onDown = (e) => { dragging = true; lastX = e.touches ? e.touches[0].clientX : e.clientX; };
    const onMove = (e) => {
      const cx = e.touches ? e.touches[0].clientX : e.clientX;
      const cy = e.touches ? e.touches[0].clientY : e.clientY;
      const rect = mount.getBoundingClientRect();
      px = ((cx - rect.left) / rect.width - 0.5) * 2;
      py = ((cy - rect.top) / rect.height - 0.5) * 2;
      if (!dragging) return;
      rotY += (cx - lastX) * 0.008;
      lastX = cx;
    };
    const onUp = () => { dragging = false; };
    mount.addEventListener("mousedown", onDown);
    mount.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    mount.addEventListener("touchstart", onDown, { passive: true });
    mount.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onUp);

    let t = 0, frame;
    const tmp = new THREE.Color();
    const animate = () => {
      t += 0.008;
      if (!dragging) rotY += rotVel;
      group.rotation.y = rotY;
      camera.position.x += (px * 0.08 - camera.position.x) * 0.03;
      camera.position.y += (0.25 - py * 0.05 - camera.position.y) * 0.03;
      camera.lookAt(0, 0.15, 0);

      const pulsing = performance.now() < pulseRef.current.until;
      const glowBoost = pulsing ? 0.5 + 0.5 * Math.sin(t * 30) : 0;
      const revealed = Math.floor(N * Math.max(0, Math.min(1, covRef.current)));
      const posAttr = geo.getAttribute("position");
      const colAttr = geo.getAttribute("color");

      for (let i = 0; i < N; i++) {
        const i3 = i * 3;
        if (i < revealed) {
          const bx = targets[i3] + Math.sin(t * 1.4 + i) * 0.004;
          const by = targets[i3+1] + Math.cos(t * 1.2 + i) * 0.004;
          const bz = targets[i3+2] + Math.sin(t * 1.1 + i * 0.7) * 0.004;
          cur[i3] += (bx - cur[i3]) * 0.05;
          cur[i3+1] += (by - cur[i3+1]) * 0.05;
          cur[i3+2] += (bz - cur[i3+2]) * 0.05;
          const target = isGold[i] ? gold : blue;
          tmp.fromArray(colors, i3);
          tmp.lerp(target, 0.04);
          if (glowBoost) tmp.lerp(new THREE.Color("#FFFFFF"), glowBoost * 0.12);
          tmp.toArray(colors, i3);
        } else {
          const a = t * 0.12 + i * 0.01;
          cur[i3] += (dust[i3] * Math.cos(a * 0.1) - cur[i3]) * 0.008 + Math.sin(t + i) * 0.0008;
          cur[i3+1] += (dust[i3+1] - cur[i3+1]) * 0.008 + Math.cos(t * 0.8 + i) * 0.0008;
          cur[i3+2] += (dust[i3+2] * Math.cos(a * 0.1) - cur[i3+2]) * 0.008;
          tmp.fromArray(colors, i3);
          tmp.lerp(dim, 0.05);
          tmp.toArray(colors, i3);
        }
      }
      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;

      let m = 0;
      while (m < pairs.length && pairs[m][2] < revealed) m++;
      for (let p = 0; p < m; p++) {
        const [i, j] = pairs[p];
        linePos[p*6] = cur[i*3]; linePos[p*6+1] = cur[i*3+1]; linePos[p*6+2] = cur[i*3+2];
        linePos[p*6+3] = cur[j*3]; linePos[p*6+4] = cur[j*3+1]; linePos[p*6+5] = cur[j*3+2];
        for (let c = 0; c < 2; c++) {
          const idx = c === 0 ? i : j;
          const col = isGold[idx] ? gold : blue;
          lineCol[p*6+c*3] = col.r * 0.45; lineCol[p*6+c*3+1] = col.g * 0.45; lineCol[p*6+c*3+2] = col.b * 0.45;
        }
      }
      lineGeo.setDrawRange(0, m * 2);
      lineGeo.getAttribute("position").needsUpdate = true;
      lineGeo.getAttribute("color").needsUpdate = true;

      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);

    const onResize = () => {
      const w2 = mount.clientWidth;
      camera.aspect = w2 / H;
      camera.updateProjectionMatrix();
      renderer.setSize(w2, H);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("touchend", onUp);
      mount.removeEventListener("mousedown", onDown);
      mount.removeEventListener("mousemove", onMove);
      mount.removeEventListener("touchstart", onDown);
      mount.removeEventListener("touchmove", onMove);
      renderer.dispose();
      geo.dispose(); mat.dispose(); lineGeo.dispose(); lineMat.dispose();
      starGeo.dispose(); starMat.dispose(); sprite.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, [height]);

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <div ref={mountRef} style={{ width: "100%", height, cursor: "grab" }} />
      {caption && (
        <div style={{ position: "absolute", bottom: 8, left: 0, right: 0, textAlign: "center", pointerEvents: "none" }}>
          <span style={{ fontSize: 10, color: T.ink4, letterSpacing: "0.08em", textTransform: "uppercase" }}>drag to look around</span>
        </div>
      )}
    </div>
  );
}

// ---------- glyph ----------
function Glyph({ params, size = 40 }) {
  const pts = useMemo(() => (params ? glyphTargets(params, 150, 150, 105, 60) : []), [params]);
  if (!params) return null;
  const hsl1 = `hsl(${params.hue1},50%,68%)`, hsl2 = `hsl(${params.hue2},42%,58%)`;
  return (
    <svg viewBox="0 0 300 300" style={{ width: size, height: size }}>
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={2} fill={i % 2 ? hsl1 : hsl2} opacity={0.55} />)}
      <circle cx="150" cy="150" r="5" fill={hsl1} opacity="0.85" />
    </svg>
  );
}

function MoodBar({ label, value, lo, hi, color }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.ink3, marginBottom: 4 }}>
        <span>{lo}</span><span style={{ color: T.ink2, fontWeight: 600, letterSpacing: "0.04em" }}>{label}</span><span>{hi}</span>
      </div>
      <div style={{ width: "100%", height: 4, background: "#1A2130", borderRadius: 4, position: "relative", overflow: "hidden" }}>
        <div style={{ width: `${value}%`, height: "100%", background: `linear-gradient(90deg, ${color}88, ${color})`, borderRadius: 4, transition: "width 0.45s cubic-bezier(.2,.8,.2,1)", boxShadow: `0 0 8px ${color}55` }} />
      </div>
    </div>
  );
}

function EvidenceDots({ count, color = T.goldBright }) {
  return (
    <span style={{ display: "inline-flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: Math.min(count, 8) }).map((_, i) => (
        <span key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}66` }} />
      ))}
      {count > 8 && <span style={{ fontSize: 10, color: T.ink3 }}>+{count - 8}</span>}
    </span>
  );
}

// ============================================================
// MAIN
// ============================================================
export default function ThirdPersona() {
  const initialPhase = (typeof window !== "undefined" && window.location.hash === "#app") ? "app" : "hero";
  const [phase, setPhase] = useState(initialPhase);
  const [obText, setObText] = useState("");
  const [tab, setTab] = useState("you");
  const [entries, setEntries] = useState(ENTRIES0);
  const [patterns, setPatterns] = useState(PATTERNS0);
  const [rejections, setRejections] = useState([]);
  const [rejectingId, setRejectingId] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [flashId, setFlashId] = useState(null);
  const [entryText, setEntryText] = useState("");
  const [pTag, setPTag] = useState("");
  const [people, setPeople] = useState([]);
  const [mood, setMood] = useState({ energy: 50, openness: 50, tension: 50 });
  const [pCtx, setPCtx] = useState("dating");
  const [traceP, setTraceP] = useState(null);
  const [circle] = useState(CIRCLE0);
  const [inviteFor, setInviteFor] = useState(null);
  const [dialogueQ, setDialogueQ] = useState(null);
  const [dialogueTyping, setDialogueTyping] = useState(false);
  const [dialogueShown, setDialogueShown] = useState("");
  const [justSaved, setJustSaved] = useState(false);
  const [pulse, setPulse] = useState(0);
  // live mode
  const [showSettings, setShowSettings] = useState(false);
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [apiUser, setApiUser] = useState("");
  const [live, setLive] = useState(false);
  const [liveErr, setLiveErr] = useState("");

  const coverage = useMemo(() => getCoverage(entries), [entries]);
  const totalCov = useMemo(() => { const v = Object.values(coverage); return Math.round(v.reduce((a,b)=>a+b,0)/v.length); }, [coverage]);
  const gaps = useMemo(() => DOMAINS.map((d) => ({ ...d, cov: coverage[d.id] || 0 })).sort((a,b) => a.cov - b.cov).slice(0, 3), [coverage]);
  const joinedCount = circle.filter((m) => m.joined).length;
  const circleUnlocked = joinedCount >= 1 && totalCov >= 15;

  const hypotheses = patterns.filter((p) => p.status === "hypothesis");
  const actives = patterns.filter((p) => p.status === "active");
  const rejectedPs = patterns.filter((p) => p.status === "rejected");
  const rejRate = patterns.length ? rejectedPs.length / patterns.length : 0;
  const breakerTripped = rejRate > 0.4 && patterns.length >= 5;

  useEffect(() => { if (entryText.length > 10) setMood(detectMood(entryText)); }, [entryText]);

  useEffect(() => {
    if (dialogueQ === null) { setDialogueShown(""); return; }
    setDialogueTyping(true); setDialogueShown("");
    const full = DIALOGUE_RESPONSES[dialogueQ].a;
    let i = 0;
    const iv = setInterval(() => {
      i += 3;
      setDialogueShown(full.slice(0, i));
      if (i >= full.length) { clearInterval(iv); setDialogueTyping(false); }
    }, 18);
    return () => clearInterval(iv);
  }, [dialogueQ]);

  // ---- live mode wiring (FastAPI backend) ----
  const api = async (path, opts = {}) => {
    const res = await fetch(`${apiBase}${path}`, {
      ...opts,
      headers: { "Content-Type": "application/json", "X-User-ID": apiUser, ...(opts.headers || {}) },
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  };
  const connectLive = async () => {
    setLiveErr("");
    try {
      const es = await api("/entries");
      const ps = await api("/patterns");
      setEntries(es.map((e) => ({ id: e.id, text: e.text_content || "", people: [], date: (e.created_at || "").slice(0, 10), mood: { energy: e.mood_energy ?? 50, openness: e.mood_openness ?? 50, tension: e.mood_tension ?? 50 } })));
      setPatterns(ps.map((p) => ({ id: p.id, status: p.status, insight: p.insight, category: p.category, evidence: Array.from({ length: p.evidence_count || 0 }, (_, i) => i), spreadDays: p.temporal_spread || 0, firstSeen: (p.created_at || "").slice(0, 10) })));
      setLive(true); setShowSettings(false);
    } catch (err) {
      setLiveErr(String(err.message || err)); setLive(false);
    }
  };

  const addEntry = async () => {
    if (!entryText.trim()) return;
    if (live) {
      try { const e = await api("/entries", { method: "POST", body: JSON.stringify({ text_content: entryText }) });
        setEntries([{ id: e.id, text: e.text_content, people: [...people], date: (e.created_at || "").slice(0, 10), mood: { ...mood } }, ...entries]);
      } catch (err) { setLiveErr(String(err.message || err)); return; }
    } else {
      setEntries([{ id: entries.length + 1, text: entryText, people: [...people], date: new Date().toISOString().split("T")[0], mood: { ...mood } }, ...entries]);
    }
    setEntryText(""); setPeople([]); setMood({ energy: 50, openness: 50, tension: 50 });
    setJustSaved(true); setPulse((p) => p + 1);
    setTimeout(() => setJustSaved(false), 3000);
  };

  const confirmPattern = async (p) => {
    if (live) { try { await api(`/patterns/${p.id}/confirm`, { method: "POST", body: JSON.stringify({}) }); } catch (err) { setLiveErr(String(err.message || err)); return; } }
    setFlashId(p.id);
    setTimeout(() => setFlashId(null), 900);
    setPatterns((ps) => ps.map((x) => x.id === p.id ? { ...x, status: "active", confirmedOn: new Date().toISOString().slice(0, 10) } : x));
  };
  const rejectPattern = async (p, reason) => {
    if (live) { try { await api(`/patterns/${p.id}/reject`, { method: "POST", body: JSON.stringify({ reason: reason || null }) }); } catch (err) { setLiveErr(String(err.message || err)); return; } }
    setPatterns((ps) => ps.map((x) => x.id === p.id ? { ...x, status: "rejected" } : x));
    setRejections((r) => [...r, { id: p.id, reason }]);
    setRejectingId(null); setRejectReason("");
  };

  const S = {
    app: { minHeight: "100vh", background: `radial-gradient(1200px 700px at 50% -10%, #0B1020 0%, ${T.bg} 55%)`, color: T.ink, fontFamily: T.sans, fontSize: 15, lineHeight: 1.6 },
    card: { background: T.glass, backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)", borderRadius: 14, padding: 18, marginBottom: 12, border: `1px solid ${T.border}`, boxShadow: "0 12px 40px rgba(0,0,0,0.35)" },
    label: { fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 14 },
    eyebrow: { fontSize: 10, color: T.gold, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase" },
    chip: (on) => ({ padding: "5px 12px", borderRadius: 20, fontSize: 11, fontWeight: 500, cursor: "pointer", background: on ? "rgba(123,142,200,0.13)" : "#131926", color: on ? T.blueBright : T.ink3, border: on ? "1px solid rgba(141,158,240,0.35)" : `1px solid ${T.borderSoft}`, fontFamily: "inherit" }),
    badge: (c) => ({ fontSize: 10, padding: "2px 9px", borderRadius: 10, background: `${c}1c`, color: c, border: `1px solid ${c}2e` }),
    btnGold: { padding: "9px 20px", background: `linear-gradient(135deg, ${T.goldBright}, ${T.gold})`, color: "#0A0C12", border: "none", borderRadius: 9, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 4px 18px rgba(201,169,110,0.25)" },
    btnGhost: { padding: "9px 18px", background: "transparent", color: T.ink3, border: `1px solid ${T.border}`, borderRadius: 9, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" },
    display: { fontFamily: T.serif, fontWeight: 500, letterSpacing: "-0.015em" },
  };

  // ===== HERO =====
  if (phase === "hero") {
    return (
      <div style={S.app}>
        <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, maxWidth: 560, margin: "0 auto", position: "relative" }}>
          <div style={{ fontSize: 12, letterSpacing: "0.3em", textTransform: "uppercase", color: T.gold, marginBottom: 8, fontWeight: 600 }}>ThirdPersona</div>
          <HumanMesh coverage={0.04} height={340} caption={false} />
          <h1 style={{ ...S.display, fontSize: 40, lineHeight: 1.15, margin: "8px 0 14px", textAlign: "center", background: `linear-gradient(135deg, ${T.ink} 30%, ${T.goldBright} 100%)`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            This is you.<br />Unwritten.
          </h1>
          <p style={{ fontSize: 15, color: T.ink2, lineHeight: 1.8, textAlign: "center", margin: "0 0 6px", maxWidth: 400 }}>
            Every honest word you write pulls a piece of you out of the dust and into form.
          </p>
          <p style={{ fontSize: 12, color: T.ink4, textAlign: "center", margin: "0 0 36px" }}>
            Know yourself first. Then connect. In that order.
          </p>
          <button onClick={() => setPhase("write")} style={{ padding: "16px 52px", background: "rgba(201,169,110,0.08)", color: T.goldBright, border: "1px solid rgba(201,169,110,0.35)", borderRadius: 12, fontSize: 15, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 0 40px rgba(201,169,110,0.10)" }}>
            Begin building yourself
          </button>
          <div style={{ position: "absolute", bottom: 20, left: 0, right: 0, textAlign: "center", color: T.ink4, fontSize: 11, letterSpacing: "0.1em" }}>
            ↓ why this exists
          </div>
        </div>

        <div style={{ maxWidth: 620, margin: "0 auto", padding: "80px 24px 100px" }}>
          <div style={{ ...S.eyebrow, marginBottom: 20, textAlign: "center" }}>
            Language was never the medium of thought
          </div>
          <h2 style={{ ...S.display, fontSize: 30, lineHeight: 1.3, marginBottom: 28, textAlign: "center", color: T.ink }}>
            Who you are doesn't live in words.<br />So we stopped asking for words.
          </h2>

          <div style={{ display: "grid", gap: 1, background: T.border, borderRadius: 14, overflow: "hidden", border: `1px solid ${T.border}`, marginBottom: 32 }}>
            {[
              { n: "39/40", l: "rule-induction problems solved by a patient with profound aphasia, despite near-chance grammar" },
              { n: "0", l: "engagement of the brain's language network during logical reasoning (fMRI, healthy adults)" },
              { n: "2 systems", l: "thought and language are distinct neural machinery, not one system" },
            ].map((s, i) => (
              <div key={i} style={{ background: T.surface, padding: "20px 22px", display: "flex", alignItems: "baseline", gap: 16 }}>
                <div style={{ ...S.display, fontSize: 24, color: T.goldBright, minWidth: 96 }}>{s.n}</div>
                <div style={{ fontSize: 13, color: T.ink2, lineHeight: 1.6 }}>{s.l}</div>
              </div>
            ))}
          </div>

          <p style={{ fontSize: 15, color: "#C6CFDA", lineHeight: 1.85, marginBottom: 20 }}>
            In 2025, researchers at MIT, UCL, and UC Berkeley showed something the rest of us feel but rarely name.
            The part of your brain that produces language is not the part that does your thinking. People with
            severe damage to their language network, unable to parse a simple sentence, still reason at or above
            normal levels. Thought runs on a structure underneath the words.
          </p>
          <p style={{ fontSize: 15, color: "#C6CFDA", lineHeight: 1.85, marginBottom: 20 }}>
            Which means every time you compress yourself into "I'm fine" or "I'm pretty easygoing," you are forcing
            a reality through a channel your brain doesn't even use to hold it. The loss is guaranteed. It's not that
            you're bad with words. It's that words were never where you lived.
          </p>
          <p style={{ fontSize: 15, color: T.ink, lineHeight: 1.85, marginBottom: 32, fontWeight: 500 }}>
            ThirdPersona reads the structure, not the sentences. It never builds a machine that talks like you and
            calls that understanding. It finds the shape underneath, and hands it back to you first.
          </p>

          <div style={{ background: T.surface, borderRadius: 12, padding: "18px 20px", border: `1px solid ${T.border}`, marginBottom: 40 }}>
            <p style={{ margin: 0, fontSize: 12.5, color: T.ink2, lineHeight: 1.7, fontStyle: "italic", fontFamily: T.serif }}>
              "Linguistic competence, by itself, is not evidence of understanding. This distinction matters in an age
              where fluent machines are increasingly mistaken for thinking ones."
            </p>
            <div style={{ fontSize: 11, color: T.ink4, marginTop: 10, lineHeight: 1.6 }}>
              Kean et al. (2025), Evidence from Formal Logical Reasoning Reveals that the Language of Thought is not
              Natural Language. bioRxiv.
            </div>
          </div>

          <div style={{ textAlign: "center" }}>
            <button onClick={() => { setPhase("write"); window.scrollTo(0, 0); }} style={{ ...S.btnGold, padding: "16px 52px", fontSize: 15 }}>
              Begin building yourself
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ===== WRITE =====
  if (phase === "write") {
    const progress = Math.min(0.22, 0.04 + (obText.length / 240) * 0.18);
    return (
      <div style={S.app}>
        <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, maxWidth: 560, margin: "0 auto" }}>
          <HumanMesh coverage={progress} height={300} caption={false} />
          <p style={{ ...S.display, fontSize: 19, color: T.ink, margin: "6px 0 4px", textAlign: "center" }}>
            Watch yourself take shape.
          </p>
          <p style={{ fontSize: 12, color: T.ink4, margin: "0 0 20px", textAlign: "center" }}>
            {obText.length < 30 ? "Mostly dust. That's honest." : obText.length < 120 ? "Something is forming." : "You're starting to exist here."}
          </p>
          <textarea autoFocus value={obText} onChange={(e) => setObText(e.target.value)} placeholder="Who are you when nobody's watching?" style={{ width: "100%", minHeight: 110, background: T.glass, backdropFilter: "blur(10px)", border: `1px solid ${T.border}`, borderRadius: 14, padding: 18, color: T.ink, fontSize: 15, fontFamily: "inherit", lineHeight: 1.7, resize: "vertical", outline: "none", boxSizing: "border-box" }} />
          <button onClick={() => { if (obText.length >= 40) setPhase("app"); }} disabled={obText.length < 40} style={{ marginTop: 20, padding: "14px 46px", background: obText.length >= 40 ? `linear-gradient(135deg, ${T.goldBright}, ${T.gold})` : "rgba(24,30,41,0.8)", color: obText.length >= 40 ? "#0A0C12" : T.ink4, border: "none", borderRadius: 10, fontSize: 14, fontWeight: 700, cursor: obText.length >= 40 ? "pointer" : "default", fontFamily: "inherit" }}>
            This is me
          </button>
        </div>
      </div>
    );
  }

  // ===== APP =====
  return (
    <div style={S.app}>
      <div style={{ padding: "14px 20px 0", maxWidth: 760, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 24, height: 24, borderRadius: "50%", background: `radial-gradient(circle at 35% 35%, ${T.goldBright}, ${T.blue})`, opacity: 0.9, boxShadow: "0 0 14px rgba(201,169,110,0.35)" }} />
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.02em" }}>ThirdPersona</span>
          {live && <span style={{ fontSize: 10, color: T.green, marginLeft: 4 }}>● live</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 11, color: T.ink3 }}>{totalCov}% of you exists here</span>
          <button onClick={() => setShowSettings(!showSettings)} title="Connect to backend" style={{ background: "none", border: "none", color: T.ink3, cursor: "pointer", fontSize: 14, fontFamily: "inherit", padding: 2 }}>⚙</button>
        </div>
      </div>

      {showSettings && (
        <div style={{ maxWidth: 760, margin: "10px auto 0", padding: "0 20px" }}>
          <div style={{ ...S.card, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, color: T.ink3, fontWeight: 600 }}>LIVE BACKEND</span>
            <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="http://localhost:8000" style={{ flex: 1, minWidth: 180, background: T.well, border: `1px solid ${T.border}`, borderRadius: 8, padding: "7px 10px", color: T.ink, fontSize: 12, outline: "none", fontFamily: "inherit" }} />
            <input value={apiUser} onChange={(e) => setApiUser(e.target.value)} placeholder="user UUID (X-User-ID)" style={{ flex: 1, minWidth: 200, background: T.well, border: `1px solid ${T.border}`, borderRadius: 8, padding: "7px 10px", color: T.ink, fontSize: 12, outline: "none", fontFamily: "inherit" }} />
            <button onClick={connectLive} style={S.btnGold}>Connect</button>
            {liveErr && <div style={{ width: "100%", fontSize: 11, color: T.red }}>{liveErr}</div>}
            <div style={{ width: "100%", fontSize: 10, color: T.ink4 }}>Demo data until connected. Point this at the FastAPI vertical slice to read and write real entries & hypotheses.</div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", borderBottom: `1px solid ${T.border}`, maxWidth: 760, margin: "10px auto 0", padding: "0 20px", overflowX: "auto" }}>
        {[["you","You"],["patterns","Hypotheses"],["circle","Circle"],["dialogue","Dialogue"],["portable","Portable You"]].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)} style={{ padding: "9px 13px", fontSize: 12, fontWeight: tab === k ? 700 : 400, color: tab === k ? T.ink : T.ink3, background: "none", border: "none", borderBottom: `2px solid ${tab === k ? T.goldBright : "transparent"}`, fontFamily: "inherit", cursor: "pointer", whiteSpace: "nowrap", transition: "color .2s" }}>
            {l}
            {k === "patterns" && hypotheses.length > 0 && <span style={{ fontSize: 9, background: T.goldBright, color: "#0A0C12", borderRadius: 8, padding: "1px 6px", marginLeft: 6, fontWeight: 700 }}>{hypotheses.length}</span>}
            {k === "dialogue" && <span style={{ fontSize: 8, color: T.goldBright, marginLeft: 4, verticalAlign: "top" }}>✦</span>}
          </button>
        ))}
      </div>

      <div style={{ maxWidth: 760, margin: "0 auto", padding: "20px 20px 80px" }}>

        {/* ===== YOU ===== */}
        {tab === "you" && (<div>
          <div style={{ ...S.card, padding: 0, overflow: "hidden", marginBottom: 20 }}>
            <HumanMesh coverage={totalCov / 100} height={360} pulse={pulse} />
            <div style={{ padding: "0 20px 18px", textAlign: "center" }}>
              <div style={{ fontSize: 14, color: T.ink, fontWeight: 600 }}>
                {totalCov}% of you exists here
                {justSaved && <span style={{ color: T.green, fontSize: 12, marginLeft: 8 }}>+ new pieces arriving</span>}
              </div>
              <div style={{ fontSize: 12, color: T.ink4, marginTop: 4 }}>
                The dust around you is everything you haven't written yet.
              </div>
            </div>
          </div>

          <div style={{ ...S.card, padding: 22, marginBottom: 20 }}>
            <textarea value={entryText} onChange={(e) => setEntryText(e.target.value)} placeholder="What happened? How did it feel? Every honest word becomes part of you." style={{ width: "100%", minHeight: 100, background: T.well, border: `1px solid ${T.border}`, borderRadius: 10, padding: 14, color: T.ink, fontSize: 14, fontFamily: "inherit", lineHeight: 1.65, resize: "vertical", outline: "none", boxSizing: "border-box" }} />
            {entryText.length > 10 && (
              <div style={{ marginTop: 14, padding: 14, background: "rgba(7,9,14,0.6)", borderRadius: 10, border: `1px solid ${T.borderSoft}` }}>
                <div style={{ ...S.eyebrow, marginBottom: 10 }}>Reading your mood from your words</div>
                <MoodBar label="Energy" value={mood.energy} lo="depleted" hi="charged" color={T.green} />
                <MoodBar label="Openness" value={mood.openness} lo="withdrawn" hi="open" color={T.blueBright} />
                <MoodBar label="Tension" value={mood.tension} lo="calm" hi="activated" color={T.red} />
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: T.ink3 }}>People:</span>
              {people.map((p, i) => <span key={i} style={S.chip(true)}>{p} <span style={{ cursor: "pointer", opacity: 0.5, marginLeft: 4 }} onClick={() => setPeople(people.filter((_, j) => j !== i))}>×</span></span>)}
              <input value={pTag} onChange={(e) => setPTag(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && pTag.trim()) { setPeople([...people, pTag.trim()]); setPTag(""); } }} placeholder="Add person..." style={{ background: T.well, border: `1px solid ${T.border}`, borderRadius: 20, padding: "4px 12px", color: T.ink, fontSize: 11, outline: "none", width: 120, fontFamily: "inherit" }} />
            </div>
            <button onClick={addEntry} style={{ ...S.btnGold, marginTop: 14 }}>
              Add to yourself
            </button>
          </div>

          {gaps.some((d) => d.cov < 60) && (
            <div style={{ ...S.card, border: "1px solid rgba(201,169,110,0.18)" }}>
              <div style={{ ...S.label, color: T.gold }}>Still dust — unwritten parts of you</div>
              {gaps.filter((d) => d.cov < 60).map((d) => (
                <div key={d.id} style={{ padding: "10px 14px", background: T.well, borderRadius: 10, marginBottom: 6, border: `1px solid ${T.borderSoft}` }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{d.label}</span>
                  <span style={{ fontSize: 11, color: T.ink4 }}> ({d.cov}%)</span>
                  <div style={{ fontSize: 12, color: T.ink2, marginTop: 4, fontStyle: "italic", fontFamily: T.serif }}>"{GAP_PROMPTS[d.id]}"</div>
                </div>
              ))}
            </div>
          )}

          <div style={S.label}>Your entries</div>
          {entries.map((e) => (
            <div key={e.id} style={S.card}>
              <p style={{ margin: "0 0 10px", fontSize: 13, lineHeight: 1.7 }}>{e.text}</p>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {e.people.map((p, i) => <span key={i} style={S.badge(T.blueBright)}>{p}</span>)}
                <span style={{ fontSize: 10, color: T.ink4, marginLeft: "auto" }}>{e.date}</span>
              </div>
            </div>
          ))}
        </div>)}

        {/* ===== HYPOTHESES (the real lifecycle) ===== */}
        {tab === "patterns" && (<div>
          <div style={{ ...S.card, padding: "14px 18px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.6 }}>
                You see every hypothesis first. Nothing becomes part of you without your explicit yes —
                <span style={{ color: T.ink }}> that rule lives in the database, not in good intentions.</span>
              </div>
            </div>
            <div style={{ minWidth: 150 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.ink3, marginBottom: 4 }}>
                <span>rejection rate</span><span style={{ color: breakerTripped ? T.red : T.ink2 }}>{Math.round(rejRate * 100)}% / 40%</span>
              </div>
              <div style={{ width: "100%", height: 4, background: "#1A2130", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${Math.min(100, (rejRate / 0.4) * 100)}%`, height: "100%", background: breakerTripped ? T.red : T.goldBright, borderRadius: 4, transition: "width .4s" }} />
              </div>
            </div>
          </div>

          {breakerTripped && (
            <div style={{ ...S.card, border: `1px solid ${T.red}44`, background: "rgba(240,126,112,0.06)" }}>
              <div style={{ fontSize: 12, color: T.red, fontWeight: 700, marginBottom: 4 }}>⏸ Discovery paused</div>
              <div style={{ fontSize: 12, color: T.ink2, lineHeight: 1.6 }}>
                Too many recent hypotheses missed. The system recalibrates from your rejections rather than guessing worse. This is by design.
              </div>
            </div>
          )}

          {hypotheses.length > 0 && <div style={S.label}>Waiting for you — {hypotheses.length}</div>}
          {hypotheses.map((p) => (
            <div key={p.id} style={{ ...S.card, borderLeft: `3px solid ${CAT_COL[p.category] || T.gold}`, transition: "box-shadow .3s, border-color .3s", ...(flashId === p.id ? { boxShadow: `0 0 30px ${T.goldBright}44` } : {}) }}>
              <div style={{ ...S.eyebrow, marginBottom: 8 }}>We noticed</div>
              <p style={{ margin: "0 0 12px", fontSize: 14, lineHeight: 1.75, fontFamily: T.serif, color: "#DAE2EC" }}>{p.insight.replace(/^We noticed( that)?\s*/i, "")}</p>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
                <span style={S.badge(CAT_COL[p.category] || T.gold)}>{p.category}</span>
                <span style={{ fontSize: 10, color: T.ink3, display: "inline-flex", alignItems: "center", gap: 6 }}>
                  evidence <EvidenceDots count={p.evidence.length} />
                </span>
                {p.spreadDays > 0 && <span style={{ fontSize: 10, color: T.ink3 }}>across {p.spreadDays} days</span>}
                <button onClick={() => setTraceP(p)} style={{ fontSize: 10, color: T.blueBright, cursor: "pointer", textDecoration: "underline", background: "none", border: "none", fontFamily: "inherit", padding: 0 }}>receipts</button>
              </div>
              {rejectingId === p.id ? (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <input autoFocus value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Why doesn't this fit? (optional — it teaches the system)" style={{ flex: 1, minWidth: 220, background: T.well, border: `1px solid ${T.border}`, borderRadius: 8, padding: "8px 12px", color: T.ink, fontSize: 12, outline: "none", fontFamily: "inherit" }} />
                  <button onClick={() => rejectPattern(p, rejectReason)} style={{ ...S.btnGhost, color: T.red, borderColor: `${T.red}44` }}>Set aside</button>
                  <button onClick={() => { setRejectingId(null); setRejectReason(""); }} style={{ ...S.btnGhost, border: "none" }}>Cancel</button>
                </div>
              ) : (
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => confirmPattern(p)} style={S.btnGold}>That's me</button>
                  <button onClick={() => setRejectingId(p.id)} style={S.btnGhost}>Not me</button>
                </div>
              )}
            </div>
          ))}

          {actives.length > 0 && <div style={{ ...S.label, marginTop: 24 }}>Part of you — confirmed by you</div>}
          {actives.map((p) => (
            <div key={p.id} style={{ ...S.card, borderLeft: `3px solid ${T.goldBright}`, ...(flashId === p.id ? { boxShadow: `0 0 30px ${T.goldBright}44` } : {}) }}>
              <p style={{ margin: "0 0 10px", fontSize: 13.5, lineHeight: 1.75, fontFamily: T.serif, color: "#DAE2EC" }}>{p.insight}</p>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span style={S.badge(T.goldBright)}>✓ confirmed{p.confirmedOn ? ` ${p.confirmedOn}` : ""}</span>
                <span style={{ fontSize: 10, color: T.ink3, display: "inline-flex", alignItems: "center", gap: 6 }}>
                  evidence <EvidenceDots count={p.evidence.length} />
                </span>
                <button onClick={() => setTraceP(p)} style={{ fontSize: 10, color: T.blueBright, cursor: "pointer", textDecoration: "underline", background: "none", border: "none", fontFamily: "inherit", padding: 0 }}>receipts</button>
              </div>
            </div>
          ))}

          {rejectedPs.length > 0 && <div style={{ ...S.label, marginTop: 24, color: T.ink4 }}>Set aside — won't be re-surfaced</div>}
          {rejectedPs.map((p) => {
            const rej = rejections.find((r) => r.id === p.id);
            return (
              <div key={p.id} style={{ ...S.card, opacity: 0.55, borderLeft: `3px solid ${T.ink4}` }}>
                <p style={{ margin: "0 0 8px", fontSize: 12.5, lineHeight: 1.7, color: T.ink3, textDecoration: "line-through", textDecorationColor: "rgba(154,166,181,0.4)" }}>{p.insight}</p>
                <div style={{ fontSize: 11, color: T.ink4 }}>
                  You said: "{(rej && rej.reason) || "not me"}" — the system learned from this and won't rediscover it.
                </div>
              </div>
            );
          })}
        </div>)}

        {/* ===== CIRCLE ===== */}
        {tab === "circle" && (<div>
          <div style={{ marginBottom: 12, display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 20, background: "rgba(201,169,110,0.08)", border: "1px solid rgba(201,169,110,0.2)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.goldBright }} />
            <span style={{ fontSize: 10, color: T.gold, fontWeight: 600, letterSpacing: "0.06em" }}>DESIGN PREVIEW — consent model still being decided</span>
          </div>
          {!circleUnlocked ? (
            <div style={{ ...S.card, padding: 32, textAlign: "center" }}>
              <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>◌</div>
              <div style={{ ...S.display, fontSize: 17, marginBottom: 8 }}>Build yourself first</div>
              <p style={{ fontSize: 13, color: T.ink2, lineHeight: 1.7, maxWidth: 380, margin: "0 auto" }}>
                Your circle opens when enough of you exists here to connect with.
                You can't share a self you haven't built. Keep writing.
              </p>
            </div>
          ) : (<>
            <div style={{ ...S.card, padding: 22 }}>
              <div style={S.label}>Your constellation — {joinedCount} of {circle.length} orbits filled</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
                {circle.map((m) => m.joined ? (
                  <div key={m.id} style={{ background: T.well, borderRadius: 12, padding: 16, border: `1px solid ${T.border}`, textAlign: "center" }}>
                    <Glyph params={glyphParams(m.glyphSeed)} size={44} />
                    <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6 }}>{m.name}</div>
                    <div style={{ fontSize: 10, color: T.green, marginTop: 2 }}>{Math.round(m.resonance * 100)}% resonance</div>
                  </div>
                ) : (
                  <div key={m.id} onClick={() => setInviteFor(m)} style={{ background: T.well, borderRadius: 12, padding: 16, border: "1.5px dashed #2A3140", textAlign: "center", cursor: "pointer" }}>
                    <div style={{ width: 44, height: 44, borderRadius: "50%", border: `1px dashed ${T.ink4}`, margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "center", color: T.ink4, fontSize: 18 }}>+</div>
                    <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6, color: T.ink4 }}>{m.name}</div>
                    <div style={{ fontSize: 10, color: "#30363D", marginTop: 2 }}>not here yet</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={S.label}>Circle patterns — {CIRCLE_PATTERNS.filter((p) => !p.locked).length} of {CIRCLE_PATTERNS.length} discovered</div>
            {CIRCLE_PATTERNS.map((cp) => !cp.locked ? (
              <div key={cp.id} style={{ ...S.card, borderLeft: `3px solid ${T.green}` }}>
                <p style={{ margin: "0 0 10px", fontSize: 13, lineHeight: 1.75, fontFamily: T.serif, color: "#DAE2EC" }}>{cp.insight}</p>
                <div style={{ display: "flex", gap: 5 }}>
                  {cp.people.map((p, i) => <span key={i} style={S.badge(p === "You" ? T.goldBright : T.blueBright)}>{p}</span>)}
                  <span style={{ ...S.badge(T.green), marginLeft: "auto" }}>discovered together</span>
                </div>
              </div>
            ) : (
              <div key={cp.id} style={{ ...S.card, borderLeft: "3px solid #2A3140" }}>
                <p style={{ margin: "0 0 10px", fontSize: 13, lineHeight: 1.75, color: T.ink4 }}>{cp.teaser}</p>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                  <div style={{ display: "flex", gap: 5 }}>{cp.people.map((p, i) => <span key={i} style={S.badge(T.ink4)}>{p}</span>)}</div>
                  <button onClick={() => setInviteFor(circle.find((m) => m.id === cp.requires[0]))} style={{ padding: "6px 14px", background: "rgba(201,169,110,0.1)", color: T.goldBright, border: "1px solid rgba(201,169,110,0.25)", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" }}>
                    🔒 Needs {cp.requires.map((r) => circle.find((m) => m.id === r)?.name).join(" + ")}
                  </button>
                </div>
                <div style={{ fontSize: 10, color: "#30363D", marginTop: 8 }}>This pattern exists in the space between you. Neither of you can see it alone.</div>
              </div>
            ))}
          </>)}
        </div>)}

        {/* ===== DIALOGUE ===== */}
        {tab === "dialogue" && (<div>
          <div style={{ marginBottom: 12, display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 12px", borderRadius: 20, background: "rgba(201,169,110,0.08)", border: "1px solid rgba(201,169,110,0.2)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.goldBright }} />
            <span style={{ fontSize: 10, color: T.gold, fontWeight: 600, letterSpacing: "0.06em" }}>DESIGN PREVIEW — consent model still being decided</span>
          </div>
          <div style={{ ...S.card, padding: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
              <Glyph params={glyphParams("maria-spontaneity-warmth-art")} size={40} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>Maria's persona <span style={{ fontSize: 9, color: T.goldBright }}>✦ Premium</span></div>
                <div style={{ fontSize: 11, color: T.green }}>● mutual trust · she sees every question you ask</div>
              </div>
            </div>
            <p style={{ fontSize: 12, color: T.ink2, lineHeight: 1.7, margin: "12px 0 0" }}>
              The conversations you need but can't start. Maria consented to this. She can ask your persona too. Nothing here is secret from her.
            </p>
          </div>
          <div style={S.label}>Ask what you can't say out loud</div>
          {DIALOGUE_SUGGESTIONS.map((q, i) => (
            <button key={i} onClick={() => setDialogueQ(i)} style={{ display: "block", width: "100%", textAlign: "left", background: dialogueQ === i ? T.surface : T.well, border: dialogueQ === i ? "1px solid rgba(201,169,110,0.3)" : `1px solid ${T.borderSoft}`, borderRadius: 12, padding: "13px 16px", marginBottom: 8, color: dialogueQ === i ? T.ink : T.ink2, fontSize: 13, fontFamily: T.serif, cursor: "pointer", lineHeight: 1.6, transition: "border-color .2s" }}>
              "{q}"
            </button>
          ))}
          {dialogueQ !== null && (
            <div style={{ ...S.card, marginTop: 16, borderLeft: `3px solid ${T.blueBright}` }}>
              <div style={{ ...S.eyebrow, color: T.blueBright, marginBottom: 10 }}>Maria's persona responds</div>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.85, color: "#C6CFDA", minHeight: 60, fontFamily: T.serif }}>
                {dialogueShown}{dialogueTyping && <span style={{ opacity: 0.5 }}>▊</span>}
              </p>
              {!dialogueTyping && (
                <div style={{ marginTop: 14, padding: "10px 14px", background: T.well, borderRadius: 8, fontSize: 11, color: T.green, lineHeight: 1.6, border: `1px solid ${T.borderSoft}` }}>
                  ✓ {DIALOGUE_RESPONSES[dialogueQ].note}
                </div>
              )}
            </div>
          )}
          <div style={{ ...S.card, background: T.well, marginTop: 16 }}>
            <div style={{ fontSize: 12, color: T.goldBright, fontWeight: 600, marginBottom: 6 }}>Mediated courage</div>
            <p style={{ margin: 0, fontSize: 12, color: T.ink2, lineHeight: 1.7 }}>
              The hardest part of a hard question is saying it to a face. These conversations usually need alcohol, crisis, or years. Here they happen on a Tuesday afternoon, sober, with full consent on both sides.
            </p>
          </div>
        </div>)}

        {/* ===== PORTABLE ===== */}
        {tab === "portable" && (<div>
          <div style={{ ...S.card, padding: 0, overflow: "hidden", textAlign: "center" }}>
            <HumanMesh coverage={totalCov / 100} height={260} caption={false} />
            <div style={{ padding: "0 20px 20px" }}>
              <div style={{ ...S.display, fontSize: 19 }}>Your portable identity</div>
              <div style={{ fontSize: 12, color: T.ink2, marginTop: 6, maxWidth: 380, margin: "6px auto 0", lineHeight: 1.6 }}>Same you, different context. The dust is real. It settles as you do.</div>
            </div>
          </div>
          <div style={S.label}>Choose a context</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8, marginBottom: 20 }}>
            {Object.entries(CONTEXTS).map(([k, c]) => (
              <div key={k} onClick={() => setPCtx(k)} style={{ background: pCtx === k ? T.surface : T.well, borderRadius: 12, padding: 14, cursor: "pointer", border: pCtx === k ? "1px solid rgba(201,169,110,0.3)" : `1px solid ${T.borderSoft}`, transition: "border-color .2s" }}>
                <div style={{ fontSize: 18, marginBottom: 4 }}>{c.icon}</div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{c.label}</div>
                <div style={{ fontSize: 10, color: T.ink3, marginTop: 2 }}>{c.desc}</div>
              </div>
            ))}
          </div>
          <div style={{ ...S.card, padding: 22 }}>
            <div style={{ ...S.eyebrow, marginBottom: 4 }}>ThirdPersona · {CONTEXTS[pCtx].label}</div>
            <div style={{ ...S.display, fontSize: 17, marginBottom: 14 }}>{CONTEXTS[pCtx].title}</div>
            {CONTEXTS[pCtx].insights.map((ins, i) => (
              <div key={i} style={{ padding: "12px 0", borderTop: i === 0 ? "none" : `1px solid ${T.borderSoft}`, fontSize: 13, lineHeight: 1.75, color: "#C6CFDA" }}>{ins}</div>
            ))}
            <div style={{ marginTop: 16, padding: "12px 16px", background: T.well, borderRadius: 10, border: `1px solid ${T.borderSoft}`, fontSize: 11, color: T.ink2, lineHeight: 1.6 }}>
              Derivative view. Recipients see patterns, never raw data.
            </div>
          </div>
        </div>)}
      </div>

      {/* Invite modal */}
      {inviteFor && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(2,4,8,0.82)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }} onClick={() => setInviteFor(null)}>
          <div style={{ background: T.surface, borderRadius: 18, padding: 28, maxWidth: 420, width: "100%", border: `1px solid ${T.border}`, textAlign: "center", boxShadow: "0 30px 80px rgba(0,0,0,0.5)" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ width: 56, height: 56, borderRadius: "50%", border: `1.5px dashed ${T.ink4}`, margin: "0 auto 16px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, color: T.ink4 }}>+</div>
            <div style={{ ...S.display, fontSize: 19, marginBottom: 8 }}>{inviteFor.name}'s orbit is empty</div>
            <p style={{ fontSize: 13, color: T.ink2, lineHeight: 1.7, marginBottom: 6 }}>
              There are truths between you and {inviteFor.name} that neither of you can see alone.
            </p>
            <p style={{ fontSize: 12, color: T.ink4, lineHeight: 1.6, marginBottom: 22 }}>
              When {inviteFor.name} joins, those patterns become visible to both of you. Only to both of you.
            </p>
            <div style={{ background: T.well, borderRadius: 12, padding: "14px 16px", marginBottom: 20, textAlign: "left", border: `1px solid ${T.borderSoft}` }}>
              <div style={{ ...S.eyebrow, marginBottom: 8 }}>Your invitation</div>
              <p style={{ margin: 0, fontSize: 12.5, color: "#C6CFDA", lineHeight: 1.7, fontStyle: "italic", fontFamily: T.serif }}>
                "I've been building who I actually am, not who I perform. There's a part of it I can't see without you. No feeds, no followers, just us. Want in?"
              </p>
            </div>
            <button style={{ ...S.btnGold, width: "100%", padding: "13px", fontSize: 13, marginBottom: 8 }}>
              Send invitation to {inviteFor.name}
            </button>
            <button onClick={() => setInviteFor(null)} style={{ width: "100%", padding: "10px", background: "none", color: T.ink4, border: "none", fontSize: 12, cursor: "pointer", fontFamily: "inherit" }}>
              Not yet
            </button>
          </div>
        </div>
      )}

      {/* Receipts modal */}
      {traceP && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(2,4,8,0.78)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20 }} onClick={() => setTraceP(null)}>
          <div style={{ background: T.surface, borderRadius: 16, padding: 24, maxWidth: 480, width: "100%", border: `1px solid ${T.border}`, maxHeight: "80vh", overflowY: "auto", boxShadow: "0 30px 80px rgba(0,0,0,0.5)" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ ...S.eyebrow, marginBottom: 6 }}>Receipts — why we think this</div>
            <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.5, marginBottom: 16, fontFamily: T.serif }}>{traceP.insight}</div>
            {(traceP.evidence || []).map((sid) => { const e = entries.find((x) => x.id === sid); if (!e) return null; return (
              <div key={sid} style={{ background: T.well, borderRadius: 10, padding: 14, marginBottom: 6, border: `1px solid ${T.borderSoft}` }}>
                <p style={{ margin: "0 0 6px", fontSize: 12, lineHeight: 1.7 }}>{e.text}</p>
                <div style={{ display: "flex", gap: 5 }}>
                  {e.people.map((p, i) => <span key={i} style={S.badge(T.blueBright)}>{p}</span>)}
                  <span style={{ fontSize: 10, color: T.ink4, marginLeft: "auto" }}>{e.date}</span>
                </div>
              </div>
            ); })}
            {(traceP.evidence || []).every((sid) => !entries.find((x) => x.id === sid)) && (
              <div style={{ fontSize: 12, color: T.ink3, padding: "8px 0" }}>
                {traceP.evidence.length} linked {traceP.evidence.length === 1 ? "entry" : "entries"} — connect live mode to read them.
              </div>
            )}
            <div style={{ marginTop: 10, fontSize: 11, color: T.ink2, lineHeight: 1.6, padding: "10px 12px", background: "rgba(24,30,41,0.4)", borderRadius: 8 }}>Only you see these sources. A pattern without receipts does not exist.</div>
          </div>
        </div>
      )}
    </div>
  );
}
