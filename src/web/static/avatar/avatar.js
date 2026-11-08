// The 3D patient. Shown above the conversation in the Session view.
//
// It never plays sound itself: session.js plays the patient's voice as before,
// and a silent copy of the same audio goes to TalkingHead, which uses it as the
// clock for the lips. The server sends each word's position in that audio
// ({"type": "word", "s": sample, "d": samples}, see pipeline/lipsync.py), so a
// word is handed over only once its audio has arrived, timed from the start of
// the stretch of speech it belongs to.
//
// The face follows the state engine: every "state" event picks a mood for the
// emotion, blends in the undertone, scales it by intensity and adds the active
// defense on top. Nothing here decides an emotion.
import { TalkingHead } from "talkinghead";

const RATE = 24000;
const DEFAULT_MODEL = { url: "/static/avatar/patient.glb", body: "F" };

// TalkingHead's built-in mood whose idle motion each emotion borrows, and the
// face (ARKit blendshapes, 0 to 1) at full intensity.
const FACES = {
  CALM:       { from: "neutral", eyes: 0.45, face: { eyesLookDown: 0.1, mouthPressLeft: 0.1, mouthPressRight: 0.1 } },
  SHOCK:      { from: "fear",    eyes: 0.1,  face: { eyeWideLeft: 0.55, eyeWideRight: 0.55, browInnerUp: 0.5, browOuterUpLeft: 0.3, browOuterUpRight: 0.3, jawOpen: 0.12, mouthFunnel: 0.1 } },
  ANGER:      { from: "angry",   eyes: 0.75, face: { browDownLeft: 0.6, browDownRight: 0.6, jawForward: 0.25, mouthFrownLeft: 0.5, mouthFrownRight: 0.5, mouthPressLeft: 0.3, mouthPressRight: 0.3, noseSneerLeft: 0.2, noseSneerRight: 0.2 } },
  GRIEF:      { from: "sad",     eyes: 0.1,  face: { eyesLookDown: 0.35, browInnerUp: 0.65, eyeSquintLeft: 0.5, eyeSquintRight: 0.5, mouthFrownLeft: 0.7, mouthFrownRight: 0.7, mouthRollLower: 0.2, mouthShrugLower: 0.3 } },
  FEAR:       { from: "fear",    eyes: 0.3,  face: { browInnerUp: 0.7, eyeWideLeft: 0.45, eyeWideRight: 0.45, mouthStretchLeft: 0.3, mouthStretchRight: 0.3, mouthShrugLower: 0.3 } },
  BARGAINING: { from: "sad",     eyes: 0.7,  face: { browInnerUp: 0.7, browOuterUpLeft: 0.2, browOuterUpRight: 0.2, mouthFrownLeft: 0.3, mouthFrownRight: 0.3, eyeSquintLeft: 0.2, eyeSquintRight: 0.2 } },
  DEFENSIVE:  { from: "angry",   eyes: 0.6,  face: { browDownLeft: 0.35, browDownRight: 0.35, mouthPressLeft: 0.5, mouthPressRight: 0.5, jawForward: 0.15, mouthRollLower: 0.2, eyeSquintLeft: 0.2, eyeSquintRight: 0.2 } },
};
// A defense is a mask over the emotion: a small, mostly one-sided adjustment.
const MASKS = {
  SARCASM:            { mouthSmileLeft: 0.35, browOuterUpLeft: 0.3, eyeSquintRight: 0.2 },
  MINIMIZING:         { mouthSmileLeft: 0.2, mouthSmileRight: 0.2 },
  INTELLECTUALIZING:  { browDownLeft: 0.15, browDownRight: 0.15, eyeSquintLeft: 0.2, eyeSquintRight: 0.2 },
  PASSIVE_AGGRESSIVE: { mouthPressLeft: 0.4, mouthPressRight: 0.4, mouthSmileRight: 0.25, browDownLeft: 0.15 },
};
const UNDERTONE = 0.35; // how much of the undertone shows, at full intensity
// A patient sits still in a consultation: only the two calm standing poses.
const POSE = { name: "pose", alt: [
  { p: 0.5, delay: [5000, 30000], vs: { pose: ["side"] } },
  { delay: [5000, 30000], vs: { pose: ["straight"] } },
] };

let head = null, loading = null, loadedUrl = null, streaming = false;
let received = 0, runStart = 0, words = [], lastState = null, moodCount = 0;
const el = (id) => document.getElementById(id);

function status(text) {
  const s = el("avatar-status");
  if (s) { s.textContent = text || ""; s.hidden = !text; }
}

function model() {
  const c = window.App && App.current && App.current();
  return { ...DEFAULT_MODEL, ...((c && c.avatar) || {}) };
}

async function load() {
  const m = model();
  if (head && loadedUrl === m.url) return head;
  if (loading) return loading;
  loading = (async () => {
    if (!head) {
      head = new TalkingHead(el("avatar"), {
        lipsyncModules: ["en"],
        lipsyncLang: "en",
        cameraView: "upper",
        cameraDistance: -0.6, // closer than "upper": face and shoulders
        cameraRotateEnable: false,
        cameraPanEnable: false,
        cameraZoomEnable: false,
        mixerGainSpeech: 0, // silent: session.js plays the voice
        avatarMood: "neutral",
      });
    }
    status("Loading the 3D patient…");
    await head.showAvatar({ url: m.url, body: m.body || "F", avatarMood: "neutral", lipsyncLang: "en" }, (ev) => {
      if (ev.lengthComputable) status(`Loading the 3D patient… ${Math.round((100 * ev.loaded) / ev.total)}%`);
    });
    loadedUrl = m.url;
    status("");
    if (lastState) face(lastState);
    return head;
  })();
  try { return await loading; }
  catch (e) { status("Could not load the 3D patient: " + e.message); throw e; }
  finally { loading = null; }
}

// ---- emotion -> face --------------------------------------------------------
function blend(target, face, k) {
  for (const [name, v] of Object.entries(face)) target[name] = Math.min(1, (target[name] || 0) + v * k);
}

function face(s) {
  lastState = s;
  if (!head || !head.armature) return;
  const main = FACES[s.emotion] || FACES.CALM;
  const under = s.undertone && s.undertone !== s.emotion ? FACES[s.undertone] : null;
  const intensity = Math.max(0, Math.min(1, Number(s.intensity) || 0.5));
  const baseline = {};
  blend(baseline, main.face, 0.35 + 0.65 * intensity);
  if (under) blend(baseline, under.face, UNDERTONE * intensity);
  if (MASKS[s.defense]) blend(baseline, MASKS[s.defense], 1);
  const from = head.animMoods[main.from] || head.animMoods.neutral;
  const name = "patient-" + (++moodCount % 2); // two slots, so each change is a new mood
  head.animMoods[name] = {
    baseline,
    speech: from.speech,
    anims: from.anims.map((a) => (a.name === "pose" ? POSE : a)),
  };
  head.avatar.avatarIdleEyeContact = main.eyes;
  head.avatar.avatarSpeakingEyeContact = Math.min(1, main.eyes + 0.2);
  head.setMood(name);
}

// ---- audio and words ----------------------------------------------------------
async function start() {
  if (!enabled()) return;
  try {
    await load();
    // gain 0: the copy only drives the lips and head; session.js is what you hear.
    await head.streamStart({ sampleRate: RATE, gain: 0, lipsyncType: "words", lipsyncLang: "en", waitForAudioChunks: true });
    streaming = true;
    received = runStart = 0; words = [];
  } catch (e) { console.warn("3D patient:", e); }
}

function audio(buf) {
  if (!streaming || !head) return;
  // A new stretch of speech starts when TalkingHead has run out of audio.
  if (!head.isSpeaking) runStart = received;
  head.streamAudio({ audio: buf.slice(0) }); // a copy: TalkingHead takes ownership
  received += buf.byteLength / 2;
  release();
}

function word(ev) {
  if (!streaming) return;
  words.push(ev);
  release();
}

// Hand over the words whose audio has arrived, timed from their stretch's start.
function release() {
  while (words.length && words[0].s < received) {
    const w = words.shift();
    if (w.s < runStart) continue; // its audio already played
    head.streamAudio({ words: [w.w], wtimes: [((w.s - runStart) * 1000) / RATE], wdurations: [(w.d * 1000) / RATE] });
  }
}

function clear() {
  if (streaming && head) head.streamInterrupt();
  received = runStart = 0; words = [];
}

function stop() {
  if (streaming && head) head.streamStop();
  streaming = false;
  received = runStart = 0; words = [];
}

function event(ev) {
  switch (ev.type) {
    case "word": word(ev); break;
    case "state": face(ev); break;
    case "clear": clear(); break;
  }
}

// ---- show / hide -------------------------------------------------------------
function enabled() {
  const box = el("avatar-on");
  return !!(box && box.checked);
}

function applyToggle() {
  const on = enabled();
  el("stage").hidden = !on;
  try { localStorage.setItem("avatar", on ? "1" : "0"); } catch (e) {}
  if (on) load().catch(() => {});
}

window.addEventListener("DOMContentLoaded", () => {
  const box = el("avatar-on");
  let saved = null;
  try { saved = localStorage.getItem("avatar"); } catch (e) {}
  box.checked = saved !== "0";
  box.onchange = applyToggle;
  el("stage").hidden = !box.checked;
  // Load once a patient is selected, so their own model is used.
  App.listeners.select.push(() => { lastState = null; if (enabled() && !(window.Session && Session.live())) load().catch(() => {}); });
  document.addEventListener("visibilitychange", () => {
    if (!head) return;
    document.visibilityState === "visible" ? head.start() : head.stop();
  });
});

// head(): the TalkingHead instance, for debugging in the browser console.
window.Avatar = { start, stop, audio, event, enabled, head: () => head };
