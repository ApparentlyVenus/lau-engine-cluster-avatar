// The 3D patient. Shown above the conversation in the Session view.
//
// It never plays sound itself: session.js plays the patient's voice as before,
// and a silent copy of the same audio goes to TalkingHead, which uses it as the
// clock for the lips. The server sends each word's position in that audio
// ({"type": "word", "s": sample, "d": samples}, see pipeline/lipsync.py), so a
// word is handed over only once its audio has arrived, timed from the start of
// the stretch of speech it belongs to.
//
// The face follows the state engine: every "state" event sets the face for the
// emotion, blends in the undertone, scales it by intensity, adds the active
// defense on top, sets posture, gaze and how much she moves, and plays a short
// reaction when an emotion or defense first appears. Nothing here decides an
// emotion. Idle motion is kept small on purpose (see STILL_POSE, headDrift).
import { TalkingHead } from "talkinghead";

const RATE = 24000;
const DEFAULT_MODEL = { url: "/static/avatar/patient.glb", body: "F" };

// The face for each emotion at full intensity (ARKit blendshapes, 0 to 1),
// plus posture (bodyRotateX: positive leans the head down), gaze (share of the
// time she looks at the doctor), how much her head moves (1 = normal), and the
// short reaction she shows when the emotion first appears.
const FACES = {
  CALM:       { eyes: 0.5,  motion: 0.6, react: null,
                face: { eyesLookDown: 0.08, mouthPressLeft: 0.12, mouthPressRight: 0.12, browInnerUp: 0.1 } },
  SHOCK:      { eyes: 0.15, motion: 0.15, react: "😳", posture: -0.03,
                face: { eyeWideLeft: 0.8, eyeWideRight: 0.8, browInnerUp: 0.75, browOuterUpLeft: 0.45, browOuterUpRight: 0.45, jawOpen: 0.18, mouthFunnel: 0.15, mouthPressLeft: 0.1, mouthPressRight: 0.1 } },
  ANGER:      { eyes: 0.85, motion: 0.9, react: "😠", posture: 0.04,
                face: { browDownLeft: 0.8, browDownRight: 0.8, jawForward: 0.3, mouthFrownLeft: 0.6, mouthFrownRight: 0.6, mouthPressLeft: 0.45, mouthPressRight: 0.45, noseSneerLeft: 0.35, noseSneerRight: 0.35, eyeSquintLeft: 0.3, eyeSquintRight: 0.3 } },
  GRIEF:      { eyes: 0.1,  motion: 0.35, react: "😔", posture: 0.12,
                face: { eyesLookDown: 0.5, browInnerUp: 0.9, eyeSquintLeft: 0.55, eyeSquintRight: 0.55, mouthFrownLeft: 0.85, mouthFrownRight: 0.85, mouthRollLower: 0.3, mouthShrugLower: 0.4, mouthPressLeft: 0.2, mouthPressRight: 0.2 } },
  FEAR:       { eyes: 0.35, motion: 0.5, react: "😬", posture: 0.03,
                face: { browInnerUp: 0.9, eyeWideLeft: 0.55, eyeWideRight: 0.55, mouthStretchLeft: 0.4, mouthStretchRight: 0.4, mouthShrugLower: 0.35, mouthPressLeft: 0.2, mouthPressRight: 0.2 } },
  BARGAINING: { eyes: 0.8,  motion: 0.6, react: "🥺", posture: -0.02,
                face: { browInnerUp: 0.85, browOuterUpLeft: 0.25, browOuterUpRight: 0.25, mouthFrownLeft: 0.4, mouthFrownRight: 0.4, eyeSquintLeft: 0.25, eyeSquintRight: 0.25 } },
  DEFENSIVE:  { eyes: 0.7,  motion: 0.6, react: "😒", posture: -0.04,
                face: { browDownLeft: 0.45, browDownRight: 0.45, mouthPressLeft: 0.65, mouthPressRight: 0.65, jawForward: 0.2, mouthRollLower: 0.3, eyeSquintLeft: 0.3, eyeSquintRight: 0.3 } },
};
// A defense is a mask over the emotion: a small, mostly one-sided adjustment.
const MASKS = {
  SARCASM:            { mouthSmileLeft: 0.45, browOuterUpLeft: 0.4, eyeSquintRight: 0.3 },
  MINIMIZING:         { mouthSmileLeft: 0.3, mouthSmileRight: 0.3 },
  INTELLECTUALIZING:  { browDownLeft: 0.2, browDownRight: 0.2, eyeSquintLeft: 0.25, eyeSquintRight: 0.25 },
  PASSIVE_AGGRESSIVE: { mouthPressLeft: 0.5, mouthPressRight: 0.5, mouthSmileRight: 0.35, browDownLeft: 0.2 },
};
// The short reaction when a defense first appears (rolling eyes, a shrug).
const MASK_REACT = { SARCASM: "🙄", MINIMIZING: "shrug", PASSIVE_AGGRESSIVE: "😒" };
const UNDERTONE = 0.4;  // how much of the undertone shows, at full intensity
const REACT_S = 1.8;    // how long a reaction lasts

// Idle motion. TalkingHead's stock moods keep the body busy: pose changes,
// wide head sweeps, random mouth and brow twitches, hand gestures while
// talking. A patient in a consultation is still, so only breathing, blinking,
// eye movement and a small head drift remain; the face carries the emotion.
const TWITCHES = new Set(["mouth", "misc"]);
const STILL_POSE = { name: "pose", alt: [{ delay: [60000, 120000], vs: { pose: ["straight"] } }] };
function headDrift(k) {
  const r = (lo, hi) => [lo * k, hi * k];
  return { name: "head",
    idle: { delay: [1000, 4000], dt: [[2500, 7000]], vs: { bodyRotateX: [r(-0.012, 0.03)], bodyRotateY: [r(-0.08, 0.08)], bodyRotateZ: [r(-0.02, 0.02)] } },
    speaking: { dt: [[400, 1500, 0]], vs: { bodyRotateX: [[...r(-0.02, 0.05), 1, 2]], bodyRotateY: [r(-0.04, 0.04)], bodyRotateZ: [r(-0.03, 0.03)] } } };
}

let head = null, loading = null, loadedUrl = null, streaming = false;
let received = 0, runStart = 0, words = [], lastState = null, moodCount = 0;
let pendingReact = null;
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
        avatarIdleHeadMove: 0.25,     // the head follows the eyes less (default 0.5)
        avatarSpeakingHeadMove: 0.35,
      });
      head.speakWithHands = () => {}; // no hand waving while she talks
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
  const previous = lastState;
  lastState = s;
  if (!head || !head.armature) return;
  const main = FACES[s.emotion] || FACES.CALM;
  const under = s.undertone && s.undertone !== s.emotion ? FACES[s.undertone] : null;
  const intensity = Math.max(0, Math.min(1, Number(s.intensity) || 0.5));
  const baseline = {};
  blend(baseline, main.face, 0.55 + 0.45 * intensity);
  if (under) blend(baseline, under.face, UNDERTONE * intensity);
  if (MASKS[s.defense]) blend(baseline, MASKS[s.defense], 1);
  if (main.posture) baseline.bodyRotateX = main.posture * (0.5 + 0.5 * intensity);
  const base = head.animMoods.neutral;
  const keep = new Set(["breathing", "eyes", "blink"]);
  const name = "patient-" + (++moodCount % 2); // two slots, so each change is a new mood
  head.animMoods[name] = {
    baseline,
    speech: base.speech,
    anims: [...base.anims.filter((a) => keep.has(a.name)), STILL_POSE, headDrift(main.motion)],
  };
  head.avatar.avatarIdleEyeContact = main.eyes;
  head.avatar.avatarSpeakingEyeContact = Math.min(1, main.eyes + 0.2);
  head.setMood(name);
  // setMood only replaces animations of the same name, so the stock mood's
  // random mouth and brow twitches would keep running: drop them.
  head.animQueue = head.animQueue.filter((x) => !TWITCHES.has(x.template.name));

  // A short reaction when an emotion or defense first appears, so the change
  // is visible at the moment the doctor's words land.
  const newEmotion = !previous || previous.emotion !== s.emotion;
  const newMask = s.defense && s.defense !== "NONE" && (!previous || previous.defense !== s.defense);
  const react = newMask && MASK_REACT[s.defense] ? MASK_REACT[s.defense] : newEmotion && intensity >= 0.35 ? main.react : null;
  if (react) reactNow(react);
}

// Reactions wait while she is talking: they would fight the lip sync.
function reactNow(react) {
  if (head.isSpeaking) { pendingReact = react; return; }
  pendingReact = null;
  try { head.playGesture(react, REACT_S); } catch (e) { console.warn("3D patient:", e); }
}

function afterSpeaking() {
  if (pendingReact) setTimeout(() => pendingReact && head && !head.isSpeaking && reactNow(pendingReact), 300);
}

// ---- audio and words ----------------------------------------------------------
async function start() {
  if (!enabled()) return;
  try {
    await load();
    // gain 0: the copy only drives the lips and head; session.js is what you hear.
    await head.streamStart({ sampleRate: RATE, gain: 0, lipsyncType: "words", lipsyncLang: "en", waitForAudioChunks: true },
      null, afterSpeaking);
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
