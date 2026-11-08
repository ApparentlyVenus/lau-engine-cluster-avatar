// Characters view: edit every field of a character's tuning file.
const Characters = (() => {
  const EMOTIONS = ["CALM", "SHOCK", "ANGER", "GRIEF", "FEAR", "BARGAINING", "DEFENSIVE"];
  const cap = (e) => e[0] + e.slice(1).toLowerCase();
  // Defaults of the optional sections (arc, speech), from the server.
  let DEFAULTS = {};
  const DEFENSES = ["SARCASM", "INTELLECTUALIZING", "MINIMIZING", "PASSIVE_AGGRESSIVE"];
  // Every behaviour the scorer flags, with a short name for compact grids.
  const FLAG_LABELS = {
    validating: "validating", silence_tolerance: "silence", premature_reassurance: "early reassurance",
    jargon: "jargon", logistics_first: "logistics first", interruption: "talking over", disrespect: "disrespect",
    names_subtext: "names the worry", removes_blame: "not your fault", checks_understanding: "checks understanding",
    repairs: "repairs", blaming: "blaming", learner_defensive: "doctor defensive", misreads_her: "misreads them",
  };
  const MODELS = [
    { value: "eleven_v3_conversational", label: "v3 conversational (performs tags)" },
    { value: "eleven_v3", label: "v3 (performs tags)" },
    { value: "eleven_flash_v2_5", label: "Flash v2.5 (fastest, tags stripped)" },
    { value: "eleven_turbo_v2_5", label: "Turbo v2.5 (tags stripped)" },
    { value: "eleven_multilingual_v2", label: "Multilingual v2 (tags stripped)" },
  ];

  const NEG = [
    { label: "Mild", trust: -0.03, sat: 0.04 },
    { label: "Moderate", trust: -0.06, sat: 0.08 },
    { label: "Severe", trust: -0.10, sat: 0.14 },
  ];
  const RELIEF = [
    { label: "Low", trust: 0.05, sat: -0.03 },
    { label: "Medium", trust: 0.10, sat: -0.08 },
    { label: "High", trust: 0.16, sat: -0.13 },
  ];
  const SILENCE = [
    { label: "Dislikes silence", trust: -0.04, sat: 0.03 },
    { label: "Neutral", trust: 0.0, sat: 0.0 },
    { label: "Appreciates silence", trust: 0.05, sat: -0.04 },
  ];
  const ESCALATION = [
    { label: "Mild", trust: -0.03, sat: 0.08 },
    { label: "Moderate", trust: -0.05, sat: 0.15 },
    { label: "Severe", trust: -0.08, sat: 0.22 },
  ];

  const bandOf = (group) => (v, d) => {
    const bands = Object.entries((d.severity_scale || DEFAULTS.severity_scale || {})[group] || {}).sort((a, b) => b[1].min - a[1].min);
    const hit = bands.find(([, b]) => v >= b.min);
    return hit ? hit[0].replace(/_/g, " ") : "";
  };

  // ---- the schema: every key of the tuning file appears here -------------
  const SECTIONS = [
    // ---- the basics: enough to make a working character -------------------
    { group: "Basics", note: "Enough to make a working character. Everything under Fine tuning has sensible defaults." },
    {
      title: "Patient",
      intro: "Who the patient is and what they know walking in. Both Claude calls read this.",
      fields: [
        { type: "text", path: "scenario.patient_name", label: "Name" },
        { type: "int", path: "scenario.age", label: "Age", min: 0, max: 120 },
        { type: "textarea", path: "scenario.prompt", label: "Scenario",
          help: "Family, work, personality, history, what they expect to hear. Keep the result out of it: the patient's voice reads this." },
        { type: "textarea", path: "scenario.clinical_facts", label: "What the doctor has to tell them", optional: true,
          help: "The result and plan. Only the scorer sees this (to recognise when the news is given); the patient never does." },
      ],
    },
    {
      title: "Voice",
      intro: "ElevenLabs voice for this patient. Only the API key stays in .env.",
      fields: [
        { type: "text", path: "voice.voice_id", label: "Voice ID", mono: true,
          help: "ElevenLabs > Voices > voice menu > Copy voice ID." },
        { type: "select", path: "voice.model", label: "Model", options: MODELS, custom: true,
          help: "v3 performs the bracket tags. Flash is fastest but reads tags aloud, so they are stripped." },
        { type: "num", path: "voice.stability", label: "Stability", min: 0, max: 1, step: 0.05, optional: true,
          help: "Lower is more expressive and less predictable. Unset uses the ElevenLabs default." },
        { type: "voiceTest" },
      ],
    },
    {
      title: "3D model",
      intro: "The 3D patient in the Session view. Mood, gaze and lip sync come from the state engine and the voice; only the body is set here.",
      fields: [
        { type: "text", path: "avatar.url", label: "Model file (.glb)", optional: true, mono: true,
          help: "Blank uses the default model. A TalkingHead-ready model with ARKit and Oculus viseme blendshapes and a Mixamo rig, under web/static/avatar/ or any URL." },
        { type: "seg", path: "avatar.body", label: "Body", options: ["F", "M"],
          help: "Which body the model has; it picks matching idle poses." },
      ],
    },
    {
      title: "Starting mood",
      intro: "Where the patient is when the doctor walks in. Before the news their emotion stays near this; once told, the emotional arc takes over.",
      fields: [
        { type: "num", path: "initial_state.trust", label: "Trust", min: 0, max: 1, step: 0.01, hint: bandOf("trust_bands"),
          presets: [{ label: "Shut down", value: 0.10 }, { label: "Distrustful", value: 0.32 }, { label: "Guarded", value: 0.57 }, { label: "Trusting", value: 0.85 }] },
        { type: "num", path: "initial_state.saturation", label: "Saturation", min: 0, max: 1, step: 0.01, hint: bandOf("saturation_bands"),
          help: "How much they have already taken in emotionally.",
          presets: [{ label: "Calm", value: 0.15 }, { label: "Strained", value: 0.45 }, { label: "Overwhelmed", value: 0.72 }, { label: "Breaking point", value: 0.93 }] },
        { type: "seg", path: "initial_state.emotion.primary", label: "Main emotion", options: ["NONE", ...EMOTIONS] },
        { type: "seg", path: "initial_state.emotion.secondary", label: "Undertone", options: ["NONE", ...EMOTIONS] },
        { type: "num", path: "initial_state.emotion.intensity", label: "Intensity", min: 0, max: 1, step: 0.05,
          presets: [{ label: "Mild", value: 0.4 }, { label: "Moderate", value: 0.65 }, { label: "Intense", value: 0.9 }] },
      ],
    },
    {
      title: "Personality",
      intro: "How guarded the patient is and how much they put up with.",
      fields: [
        { type: "seg", path: "personality.preferred_defense_mode", label: "Defense", options: DEFENSES,
          help: "What they reach for once trust falls below the threshold." },
        { type: "num", path: "personality.defense_trigger_trust", label: "Defense threshold", min: 0, max: 1, step: 0.01,
          help: "The defense switches on when trust drops below this. Higher means they guard themselves sooner.",
          presets: [{ label: "Rarely defensive", value: 0.20 }, { label: "Normal", value: 0.35 }, { label: "Quick to guard", value: 0.45 }] },
        { type: "int", path: "personality.unacknowledged_threshold", label: "Patience (turns)", min: 1, max: 20,
          help: "Turns in a row where the doctor does not acknowledge their feelings before they escalate." },
        { type: "pair", paths: ["personality.trust_penalty", "personality.saturation_penalty"], label: "Escalation",
          help: "Applied once when patience runs out, then the count restarts.", presets: ESCALATION },
      ],
    },
    {
      title: "How the doctor's behaviour lands",
      intro: "For each behaviour Claude flags in the doctor's turn: the change to trust and saturation at full strength (scaled by the flag's 0 to 1 intensity), and whether it counts as acknowledging the patient. The presets are a good start.",
      fields: [
        { type: "flag", name: "validating", label: "Validating their feelings", presets: RELIEF },
        { type: "flag", name: "silence_tolerance", label: "Leaving space / silence", presets: SILENCE },
        { type: "flag", name: "names_subtext", label: "Naming the worry underneath", presets: RELIEF },
        { type: "flag", name: "removes_blame", label: "Saying it is not their fault", presets: RELIEF },
        { type: "flag", name: "checks_understanding", label: "Checking what they understood", presets: RELIEF },
        { type: "flag", name: "repairs", label: "Owning and fixing a misstep", presets: RELIEF },
        { type: "flag", name: "premature_reassurance", label: "Reassuring too early", presets: NEG },
        { type: "flag", name: "jargon", label: "Medical jargon", presets: NEG },
        { type: "flag", name: "logistics_first", label: "Logistics before feelings", presets: NEG },
        { type: "flag", name: "interruption", label: "Talking over them", presets: NEG },
        { type: "flag", name: "blaming", label: "Implying they caused it", presets: NEG },
        { type: "flag", name: "learner_defensive", label: "Doctor defends themselves", presets: NEG },
        { type: "flag", name: "misreads_her", label: "Misreading their reaction", presets: NEG },
        { type: "flag", name: "disrespect", label: "Disrespect or abuse", range: 1 },
      ],
    },
    {
      title: "Audio tags",
      intro: "Delivery tags the renderer may use for each emotion. v3 voices perform them; Flash strips them.",
      fields: EMOTIONS.map((e) => ({ type: "tags", path: `audio_tags.${e}`, label: cap(e) })),
    },

    // ---- fine tuning: optional, defaults shown as placeholders -------------
    { group: "Fine tuning", note: "Optional. Blank fields use the default shown in grey." },
    {
      title: "Starting mood details",
      collapsed: true,
      fields: [
        { type: "num", path: "initial_state.emotion.blend_weight", label: "Undertone strength", min: 0, max: 1, step: 0.05,
          help: "How much the undertone bleeds into the main emotion.",
          presets: [{ label: "Subtle", value: 0.1 }, { label: "Balanced", value: 0.3 }, { label: "Strong", value: 0.5 }] },
        { type: "num", path: "initial_state.competence", label: "How they rate the doctor", min: 0, max: 1, step: 0.05, optional: true,
          help: "Starting opinion of the doctor's competence. Clear answers raise it; jargon, empty reassurance and contempt lower it. Low competence feeds their anxiety." },
        { type: "seg", path: "initial_state.defense.mode", label: "Starting defense", options: ["NONE", ...DEFENSES] },
        { type: "seg", path: "initial_state.defense.masking", label: "Emotion the defense hides", options: ["NONE", ...EMOTIONS] },
        { type: "num", path: "personality.acknowledgment_intensity_threshold", label: "Acknowledgment threshold", min: 0, max: 1, step: 0.05,
          help: "An acknowledging behaviour only resets their patience when its intensity is at least this." },
      ],
    },
    {
      title: "Unanswered questions",
      collapsed: true,
      intro: "When the doctor keeps talking past the patient's questions.",
      fields: [
        { type: "int", path: "arc.frustration_after", label: "Unanswered questions before frustration", min: 0, max: 10, optional: true,
          help: "Questions in a row the doctor talks past. Past this, each further one costs trust and the patient turns passive-aggressive. 0 = off." },
        { type: "num", path: "arc.frustration_trust", label: "...trust lost per further unanswered question", min: -0.5, max: 0, step: 0.01, optional: true },
        { type: "num", path: "arc.frustration_saturation", label: "...saturation added per further unanswered question", min: 0, max: 0.5, step: 0.01, optional: true },
      ],
    },
    {
      title: "Blame and defensiveness",
      collapsed: true,
      intro: "Blame builds when the doctor implies the patient caused it and eases when they say it is not their fault. The defensive score is the blame level times the defensive weight.",
      fields: [
        { type: "num", path: "arc.blame_gain", label: "Blame added by a full-strength blaming turn", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.blame_relief", label: "Blame removed by \"not your fault\"", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.blame_decay", label: "Blame fades per turn by (fraction)", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.weights.DEFENSIVE", label: "Weight: defensive", min: 0, max: 3, step: 0.1, optional: true },
      ],
    },
    {
      title: "Reactions by state",
      collapsed: true,
      intro: "The same words land differently depending on where the patient is. Each number multiplies that behaviour's trust and saturation change while they are in that emotion or defense (1 = no change).",
      fields: [...EMOTIONS, ...DEFENSES].map((st) => ({ type: "reactions", state: st, label: cap(st).replace(/_/g, " ") })),
    },
    {
      title: "Emotional arc",
      collapsed: true,
      intro: "How the patient's emotions move once they are told. Each emotion's score comes from trust, saturation, how they rate the doctor and shock; the two strongest become the emotion and undertone.",
      fields: [
        { type: "num", path: "arc.disclosure.saturation", label: "Impact of the news on saturation", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.disclosure.trust", label: "Impact of the news on trust", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.shock_peak", label: "Shock when told", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.shock_decay", label: "Shock fades per turn by", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.shock_relief.validating", label: "...faster with validation", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.shock_relief.silence_tolerance", label: "...faster with silence", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.shock_prolong.logistics_first", label: "...slower when rushed to logistics", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.shock_prolong.jargon", label: "...slower with jargon", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.pre_news_anxiety", label: "Anxiety before the news", min: 0, max: 1, step: 0.05, optional: true },
        { type: "num", path: "arc.weights.CALM", label: "Weight: calm", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.weights.SHOCK", label: "Weight: shock", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.weights.ANGER", label: "Weight: anger", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.weights.GRIEF", label: "Weight: grief", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.weights.FEAR", label: "Weight: fear / anxiety", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.weights.BARGAINING", label: "Weight: bargaining", min: 0, max: 3, step: 0.1, optional: true },
        { type: "num", path: "arc.walkout_trust", label: "Walks out when trust stays at or below", min: 0, max: 0.5, step: 0.01, optional: true },
        { type: "int", path: "arc.walkout_turns", label: "...for this many turns (0 = never)", min: 0, max: 10, optional: true },
      ],
    },
    {
      title: "How they rate the doctor",
      collapsed: true,
      intro: "Change to the patient's opinion of the doctor's competence per behaviour, at full strength.",
      fields: [
        { type: "num", path: "arc.competence_deltas.answers_question", label: "Answering their question", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.validating", label: "Validating", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.checks_understanding", label: "Checking understanding", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.repairs", label: "Repairing a misstep", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.jargon", label: "Jargon", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.premature_reassurance", label: "Empty reassurance", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.learner_defensive", label: "Defending themselves", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.blaming", label: "Blaming the patient", min: -0.5, max: 0.5, step: 0.01, optional: true },
        { type: "num", path: "arc.competence_deltas.disrespect", label: "Disrespect", min: -0.5, max: 0.5, step: 0.01, optional: true },
      ],
    },
    {
      title: "How they speak",
      collapsed: true,
      intro: "Per emotion: an extra pause before answering (scaled by intensity), voice speed (Flash/Turbo only; v3 ignores it), voice stability, and a description of their speech the renderer follows.",
      fields: EMOTIONS.flatMap((e) => [
        { type: "num", path: `speech.${e}.reply_delay_s`, label: `${cap(e)}: pause before answering`, min: 0, max: 4, step: 0.1, unit: "s", optional: true },
        { type: "num", path: `speech.${e}.speed`, label: `${cap(e)}: speed`, min: 0.7, max: 1.2, step: 0.01, optional: true },
        { type: "num", path: `speech.${e}.stability`, label: `${cap(e)}: stability`, min: 0, max: 1, step: 0.05, optional: true },
        { type: "textarea", path: `speech.${e}.style`, label: `${cap(e)}: how they speak`, optional: true, rows: 2 },
      ]),
    },
    {
      title: "When they cut the doctor off",
      collapsed: true,
      intro: "While the doctor is speaking the patient may interrupt with a short line. The chance is base probability times their intensity, checked only when every condition holds.",
      fields: [
        { type: "multi", path: "interruption.trigger_emotions", label: "Only when their main emotion is", options: EMOTIONS },
        { type: "num", path: "interruption.min_intensity", label: "Minimum intensity", min: 0, max: 1, step: 0.05 },
        { type: "num", path: "interruption.min_seconds_before_interrupt", label: "Doctor has been talking for at least", min: 0, max: 30, step: 0.5, unit: "s" },
        { type: "num", path: "interruption.cooldown_seconds", label: "Cooldown between interruptions", min: 0, max: 60, step: 1, unit: "s" },
        { type: "num", path: "interruption.base_probability", label: "Base probability", min: 0, max: 1, step: 0.05 },
      ],
    },
    {
      title: "Trust and saturation bands",
      collapsed: true,
      intro: "Named ranges and the description Claude reads for each. Ranges should cover 0 to 1 without gaps. Untouched, the defaults are used.",
      fields: [
        { type: "bands", path: "severity_scale.trust_bands", label: "Trust" },
        { type: "bands", path: "severity_scale.saturation_bands", label: "Saturation" },
      ],
    },
    {
      title: "Turn timing",
      collapsed: true,
      intro: "How the doctor's speech is measured and when the patient's reply is released.",
      fields: [
        { type: "num", path: "timing.pause_threshold_s", label: "Pause shown from", min: 0, max: 3, step: 0.1, unit: "s", optional: true, def: 0.7,
          help: "A gap between words at least this long is marked [pause Ns] for Claude." },
        { type: "num", path: "timing.slow_wpm", label: "Slow below", min: 40, max: 200, step: 5, unit: "wpm", optional: true, def: 100 },
        { type: "num", path: "timing.fast_wpm", label: "Fast above", min: 100, max: 300, step: 5, unit: "wpm", optional: true, def: 180 },
        { type: "int", path: "timing.min_words_for_rate", label: "Words needed for a rate", min: 1, max: 30, optional: true, def: 6 },
        { type: "num", path: "timing.talk_over_min_bot_speaking_s", label: "Talk-over counts after the patient has spoken for", min: 0, max: 5, step: 0.1, unit: "s", optional: true, def: 1.0 },
        { type: "num", path: "timing.talk_over_flag", label: "Talk-over flag strength", min: 0, max: 1, step: 0.05, optional: true, def: 1.0 },
        { type: "num", path: "timing.commit_after_s", label: "Reply waits for quiet of", min: 0, max: 4, step: 0.1, unit: "s", optional: true, def: 1.0,
          help: "If the doctor speaks again before this, the turn reopens and merges." },
        { type: "num", path: "timing.commit_after_unfinished_s", label: "...when the turn sounds unfinished", min: 0, max: 6, step: 0.1, unit: "s", optional: true, def: 2.5,
          help: "Turn ends on \"uh\", \"and\", \"the\", a comma..." },
      ],
    },
  ];

  // ---- state ---------------------------------------------------------------
  const openState = SECTIONS.map((s) => !s.collapsed);
  let id = null, saved = null, draft = null, check = { errors: [], warnings: [] }, checkTimer = null, loading = 0;
  const dirty = () => draft && JSON.stringify(draft) !== JSON.stringify(saved);

  const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
  const defaultFor = (p) => get(DEFAULTS, p);
  // A value as the session will see it: the file's, else the default.
  const valueOf = (p) => get(draft, p) ?? defaultFor(p);
  // Objects that are optional in a file but must be whole once written: the
  // first edit inside one copies the default in, so nothing half-set is saved.
  const WHOLE = [/^flag_deltas\.[a-z_]+/, /^severity_scale$/];
  function set(o, p, v) {
    const ks = p.split(".");
    let a = o;
    for (const k of ks.slice(0, -1)) a = a[k] = a[k] && typeof a[k] === "object" ? a[k] : {};
    if (v === undefined) delete a[ks.at(-1)]; else a[ks.at(-1)] = v;
    // Drop sections that became empty (an all-default timing block).
    if (v === undefined && ks.length === 2 && Object.keys(a).length === 0) delete o[ks[0]];
  }
  const round = (v) => Math.round(v * 1000) / 1000;
  const fmt = (v) => (v > 0 ? "+" : "") + (+v).toFixed(2);

  // ---- rendering -----------------------------------------------------------
  function render() {
    const ed = $("editor");
    if (!draft) { ed.innerHTML = '<div class="section"><p class="empty">Loading…</p></div>'; return; }
    ed.innerHTML = "";
    SECTIONS.forEach((sec, i) => {
      if (sec.group) {
        const g = document.createElement("div");
        g.className = "group";
        g.innerHTML = `<h2>${esc(sec.group)}</h2>` + (sec.note ? `<p>${esc(sec.note)}</p>` : "");
        ed.appendChild(g);
        return;
      }
      const box = document.createElement("details");
      box.className = "section";
      box.open = openState[i];
      box.addEventListener("toggle", () => (openState[i] = box.open));
      box.innerHTML = `<summary><h3>${esc(sec.title)}</h3></summary>` + (sec.intro ? `<p class="intro">${esc(sec.intro)}</p>` : "");
      sec.fields.forEach((f) => box.appendChild(renderField(f)));
      ed.appendChild(box);
    });
  }

  function shell(f, inner) {
    const el = document.createElement("div");
    el.className = "field";
    el.innerHTML = `<div class="label"><b>${esc(f.label || "")}</b>${f.path ? `<code>${esc(f.path)}</code>` : ""}</div>` +
      (f.help ? `<div class="help">${esc(f.help)}</div>` : "") + `<div class="control"></div>`;
    inner(el.querySelector(".control"), el);
    return el;
  }

  function update(path, value) {
    for (const re of WHOLE) {
      const m = path.match(re);
      if (m && get(draft, m[0]) === undefined && defaultFor(m[0]) !== undefined) set(draft, m[0], structuredClone(defaultFor(m[0])));
    }
    set(draft, path, value);
    changed();
  }

  function renderField(f) {
    switch (f.type) {
      case "text":
        return shell(f, (c) => {
          const i = document.createElement("input");
          i.type = "text"; i.value = get(draft, f.path) ?? "";
          i.style.width = f.mono ? (f.optional ? "40ch" : "26ch") : "100%";
          if (f.mono) i.style.fontFamily = "ui-monospace, monospace";
          if (f.optional && defaultFor(f.path) !== undefined) i.placeholder = String(defaultFor(f.path));
          i.oninput = () => {
            const v = f.mono ? i.value.trim() : i.value;
            update(f.path, f.optional && !v ? undefined : v);
          };
          c.appendChild(i);
        });
      case "textarea":
        return shell(f, (c) => {
          const t = document.createElement("textarea");
          t.value = get(draft, f.path) ?? "";
          if (f.rows) t.style.minHeight = `${f.rows * 1.6 + 1}em`;
          const d = defaultFor(f.path);
          if (d !== undefined) t.placeholder = String(d);
          t.oninput = () => update(f.path, f.optional && t.value.trim() === "" ? undefined : t.value);
          c.appendChild(t);
        });
      case "int":
      case "num":
        return numField(f);
      case "seg":
        return shell(f, (c) => {
          const seg = document.createElement("div");
          seg.className = "seg";
          for (const opt of f.options) {
            const b = document.createElement("button");
            b.type = "button"; b.textContent = opt.toLowerCase();
            b.className = get(draft, f.path) === opt ? "on" : "";
            b.onclick = () => { update(f.path, opt); [...seg.children].forEach((x) => (x.className = x === b ? "on" : "")); };
            seg.appendChild(b);
          }
          c.appendChild(seg);
        });
      case "multi":
        return shell(f, (c) => {
          const seg = document.createElement("div");
          seg.className = "seg";
          for (const opt of f.options) {
            const b = document.createElement("button");
            b.type = "button"; b.textContent = opt.toLowerCase();
            const cur = () => get(draft, f.path) || [];
            b.className = cur().includes(opt) ? "on" : "";
            b.onclick = () => {
              const now = cur().includes(opt) ? cur().filter((x) => x !== opt) : [...cur(), opt];
              update(f.path, f.options.filter((x) => now.includes(x)));
              b.className = now.includes(opt) ? "on" : "";
            };
            seg.appendChild(b);
          }
          c.appendChild(seg);
        });
      case "select":
        return shell(f, (c) => {
          const s = document.createElement("select");
          const cur = get(draft, f.path) || "";
          const opts = [...f.options];
          if (cur && !opts.some((o) => o.value === cur)) opts.push({ value: cur, label: cur });
          s.innerHTML = opts.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("") +
            (f.custom ? '<option value="__custom">Other model id…</option>' : "");
          s.value = cur || opts[0].value;
          s.onchange = () => {
            if (s.value === "__custom") {
              const v = prompt("ElevenLabs model id", cur);
              if (v && v.trim()) update(f.path, v.trim());
              render();
            } else update(f.path, s.value);
          };
          c.appendChild(s);
        });
      case "flag":
        return flagField(f);
      case "pair":
        return pairField(f);
      case "tags":
        return tagsField(f);
      case "bands":
        return bandsField(f);
      case "voiceTest":
        return voiceTestField();
      case "reactions":
        return reactionsField(f);
    }
  }

  function numField(f) {
    return shell(f, (c, el) => {
      const isInt = f.type === "int";
      const cur = get(draft, f.path);
      const box = document.createElement("input");
      box.type = "number"; box.min = f.min; box.max = f.max; box.step = isInt ? 1 : f.step;
      box.value = cur ?? "";
      const def = f.def !== undefined ? f.def : defaultFor(f.path);
      if (f.optional) box.placeholder = def !== undefined && def !== null ? String(def) : "default";
      let slider = null;
      if (!isInt) {
        slider = document.createElement("input");
        slider.type = "range"; slider.min = f.min; slider.max = f.max; slider.step = f.step;
        slider.value = cur ?? def ?? (f.min + f.max) / 2;
        if (cur == null) slider.style.opacity = 0.4;
        c.appendChild(slider);
      }
      c.appendChild(box);
      const unit = f.unit ? Object.assign(document.createElement("span"), { className: "hint", textContent: f.unit }) : null;
      if (unit) { unit.style.minWidth = "auto"; c.appendChild(unit); }
      const hint = document.createElement("span");
      hint.className = "hint";
      if (f.hint) c.appendChild(hint);

      let presetsEl = null;
      if (f.presets) {
        presetsEl = document.createElement("div");
        presetsEl.className = "presets";
        el.appendChild(presetsEl);
      }

      const paint = () => {
        const v = get(draft, f.path);
        if (f.hint) hint.textContent = v == null ? "" : f.hint(v, draft);
        if (presetsEl) [...presetsEl.children].forEach((b, i) => (b.className = v === f.presets[i].value ? "on" : ""));
        if (slider) slider.style.opacity = v == null ? 0.4 : 1;
      };
      const write = (raw, from) => {
        if (raw === "" || raw == null) {
          if (f.optional) { update(f.path, undefined); paint(); }
          return;
        }
        let v = isInt ? parseInt(raw, 10) : round(parseFloat(raw));
        if (Number.isNaN(v)) return;
        update(f.path, v);
        if (from !== box) box.value = v;
        if (slider && from !== slider) slider.value = v;
        paint();
      };
      box.oninput = () => write(box.value, box);
      if (slider) slider.oninput = () => write(slider.value, slider);
      if (f.presets) {
        for (const p of f.presets) {
          const b = document.createElement("button");
          b.type = "button"; b.textContent = `${p.label} ${p.value}`;
          b.onclick = () => write(p.value, null);
          presetsEl.appendChild(b);
        }
      }
      if (f.optional) {
        const clr = document.createElement("button");
        clr.type = "button"; clr.className = "small ghost"; clr.textContent = "default";
        clr.title = "Remove this key so the default applies";
        clr.onclick = () => { box.value = ""; write("", null); };
        c.appendChild(clr);
      }
      paint();
    });
  }

  function deltaControl(label, path, range, onChange) {
    const lab = document.createElement("label");
    const v = valueOf(path) ?? 0;
    lab.innerHTML = `<span style="min-width:66px">${label}</span>`;
    const slider = Object.assign(document.createElement("input"), { type: "range", min: -range, max: range, step: 0.01, value: v });
    const box = Object.assign(document.createElement("input"), { type: "number", min: -range, max: range, step: 0.01, value: v });
    box.style.width = "74px";
    const color = () => { box.className = +box.value > 0 ? "delta-up" : +box.value < 0 ? "delta-down" : ""; };
    const write = (raw, from) => {
      const n = round(parseFloat(raw));
      if (Number.isNaN(n)) return;
      if (from !== slider) slider.value = n;
      if (from !== box) box.value = n;
      color();
      update(path, n);
      onChange && onChange();
    };
    slider.oninput = () => write(slider.value, slider);
    box.oninput = () => write(box.value, box);
    color();
    lab.append(slider, box);
    lab.setValue = (n) => write(n, null);
    return lab;
  }

  function pairBody(el, paths, presets, range, ackPath) {
    const pair = document.createElement("div");
    pair.className = "pair";
    let presetsEl;
    const paint = () => {
      if (!presetsEl) return;
      const t = valueOf(paths[0]), s = valueOf(paths[1]);
      [...presetsEl.children].forEach((b, i) => (b.className = presets[i].trust === t && presets[i].sat === s ? "on" : ""));
    };
    const tr = deltaControl("trust", paths[0], range, paint);
    const sa = deltaControl("saturation", paths[1], range, paint);
    pair.append(tr, sa);
    if (ackPath) {
      const ack = document.createElement("label");
      const cb = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!valueOf(ackPath) });
      cb.onchange = () => update(ackPath, cb.checked);
      ack.append(cb, document.createTextNode("acknowledges them"));
      pair.appendChild(ack);
    } else pair.appendChild(document.createElement("span"));
    el.appendChild(pair);
    if (presets) {
      presetsEl = document.createElement("div");
      presetsEl.className = "presets";
      for (const p of presets) {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = p.label;
        b.title = `trust ${fmt(p.trust)}, saturation ${fmt(p.sat)}`;
        b.onclick = () => { tr.setValue(p.trust); sa.setValue(p.sat); paint(); };
        presetsEl.appendChild(b);
      }
      el.appendChild(presetsEl);
      paint();
    }
  }

  function flagField(f) {
    const el = document.createElement("div");
    el.className = "flag";
    el.innerHTML = `<div class="label" style="display:flex;justify-content:space-between"><b>${esc(f.label)}</b><code style="color:var(--muted);font-size:11px">flag_deltas.${f.name}</code></div>`;
    const base = `flag_deltas.${f.name}`;
    pairBody(el, [`${base}.trust`, `${base}.saturation`], f.presets, f.range || 0.5, `${base}.acknowledges`);
    return el;
  }

  function reactionsField(f) {
    return shell(f, (c) => {
      const grid = document.createElement("div");
      grid.className = "react-grid";
      for (const [flag, short] of Object.entries(FLAG_LABELS)) {
        const path = `reactions.${f.state}.${flag}`;
        const lab = document.createElement("label");
        const box = Object.assign(document.createElement("input"), { type: "number", min: 0, max: 3, step: 0.1 });
        const cur = get(draft, path);
        if (cur !== undefined) box.value = cur;
        box.placeholder = String(defaultFor(path) ?? 1);
        box.oninput = () => {
          const n = parseFloat(box.value);
          update(path, box.value.trim() === "" || Number.isNaN(n) ? undefined : round(n));
          if (get(draft, `reactions.${f.state}`) && !Object.keys(get(draft, `reactions.${f.state}`)).length) set(draft, `reactions.${f.state}`, undefined);
        };
        lab.append(document.createTextNode(short), box);
        grid.appendChild(lab);
      }
      c.appendChild(grid);
    });
  }

  function pairField(f) {
    return shell(f, (c, el) => { c.remove(); pairBody(el, f.paths, f.presets, f.range || 0.5, null); });
  }

  function tagsField(f) {
    return shell(f, (c) => {
      const wrap = document.createElement("div");
      wrap.className = "tags";
      const draw = () => {
        const tags = get(draft, f.path) || [];
        wrap.innerHTML = "";
        tags.forEach((t, i) => {
          const s = document.createElement("span");
          s.textContent = t;
          const x = Object.assign(document.createElement("button"), { type: "button", textContent: "×", title: "Remove" });
          x.onclick = () => { update(f.path, tags.filter((_, j) => j !== i)); draw(); };
          s.appendChild(x);
          wrap.appendChild(s);
        });
        const inp = Object.assign(document.createElement("input"), { type: "text", placeholder: "add tag, Enter" });
        inp.onkeydown = (e) => {
          if (e.key !== "Enter") return;
          e.preventDefault();
          let v = inp.value.trim().replace(/^\[|\]$/g, "").trim();
          if (!v) return;
          v = `[${v}]`;
          if (!tags.includes(v)) update(f.path, [...tags, v]);
          draw();
          wrap.querySelector("input").focus();
        };
        wrap.appendChild(inp);
      };
      draw();
      c.appendChild(wrap);
    });
  }

  function bandsField(f) {
    return shell(f, (c) => {
      const bands = valueOf(f.path) || {};
      const t = document.createElement("table");
      t.className = "bands";
      for (const [name, b] of Object.entries(bands).sort((x, y) => y[1].min - x[1].min)) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(name.replace(/_/g, " "))}</td>`;
        const td = document.createElement("td");
        const mk = (key) => {
          const i = Object.assign(document.createElement("input"), { type: "number", min: 0, max: 1, step: 0.01, value: b[key] });
          i.oninput = () => { const n = parseFloat(i.value); if (!Number.isNaN(n)) update(`${f.path}.${name}.${key}`, round(n)); };
          return i;
        };
        td.append(mk("min"), document.createTextNode(" to "), mk("max"));
        td.style.whiteSpace = "nowrap";
        const td2 = document.createElement("td");
        const d = Object.assign(document.createElement("input"), { type: "text", value: b.description || "" });
        d.oninput = () => update(`${f.path}.${name}.description`, d.value);
        td2.appendChild(d);
        tr.append(td, td2);
        t.appendChild(tr);
      }
      c.appendChild(t);
      c.style.display = "block";
    });
  }

  function voiceTestField() {
    return shell({ label: "Hear it", help: "Speaks a line with the settings above (saved or not). Uses a few ElevenLabs characters." }, (c) => {
      const line = Object.assign(document.createElement("input"), { type: "text", value: "[sighs] I came here thinking it was nothing." });
      line.style.flex = "1";
      const b = Object.assign(document.createElement("button"), { type: "button", textContent: "Play" });
      const msg = Object.assign(document.createElement("span"), { className: "hint" });
      b.onclick = async () => {
        b.disabled = true; msg.textContent = "generating…";
        try {
          const blob = await App.api("POST", "/api/voice-test", { voice: draft.voice || {}, text: line.value });
          const audio = new Audio(URL.createObjectURL(blob));
          await audio.play();
          msg.textContent = "";
        } catch (e) {
          msg.textContent = e.message;
        } finally { b.disabled = false; }
      };
      c.append(line, b, msg);
    });
  }

  // ---- status panel ----------------------------------------------------------
  function changed() {
    paintStatus();
    clearTimeout(checkTimer);
    checkTimer = setTimeout(runCheck, 250);
  }

  async function runCheck() {
    if (!draft) return;
    try { check = await App.api("POST", "/api/validate", draft); } catch (e) { check = { errors: [e.message], warnings: [] }; }
    paintStatus();
  }

  function paintStatus() {
    if (!draft) return;
    const s = draft.scenario || {};
    $("st-name").textContent = (s.patient_name || "Unnamed") + (dirty() ? " •" : "");
    $("st-file").textContent = id ? `${id}.json` + (dirty() ? " · unsaved changes" : " · saved") : "";
    const errs = check.errors || [], warns = check.warnings || [];
    $("st-check").innerHTML =
      (errs.length ? `<ul class="errs">${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : '<div class="okline">Valid</div>') +
      (warns.length ? `<ul class="warns">${warns.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : "");
    const ro = App.config.read_only;
    if (ro) $("st-check").insertAdjacentHTML("beforeend", '<div class="sub" style="margin-top:6px">Editing is off on this deployment. You can change fields to try them, export the JSON, or play a voice, but not save.</div>');
    for (const b of ["delete", "new-char", "duplicate", "import-char"]) $(b).disabled = !!ro;
    $("save").disabled = ro || !dirty() || errs.length > 0;
    $("revert").disabled = !dirty();
    const st = draft.initial_state || {}, p = draft.personality || {}, em = st.emotion || {};
    const rows = [
      ["Trust", st.trust != null ? `${st.trust} ${bandOf("trust_bands")(st.trust, draft)}` : "–"],
      ["Saturation", st.saturation != null ? `${st.saturation} ${bandOf("saturation_bands")(st.saturation, draft)}` : "–"],
      ["Emotion", `${(em.primary || "–").toLowerCase()} / ${(em.secondary || "–").toLowerCase()}`],
      ["Defense", `${(p.preferred_defense_mode || "–").toLowerCase()} below ${p.defense_trigger_trust ?? "–"}`],
      ["Patience", `${p.unacknowledged_threshold ?? "–"} turns`],
      ["Voice", (draft.voice || {}).voice_id ? (draft.voice.model || "default model") : "none"],
    ];
    $("st-summary").innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
  }

  // ---- loading and actions ---------------------------------------------------
  async function load(charId) {
    const token = ++loading;
    id = charId; draft = null; render();
    try {
      const data = await App.api("GET", `/api/characters/${encodeURIComponent(charId)}`);
      if (token !== loading) return;
      saved = data; draft = structuredClone(data);
    } catch (e) {
      if (token !== loading) return;
      saved = null; draft = null;
      $("editor").innerHTML = `<div class="section"><p class="cut">${esc(e.message)}</p></div>`;
      return;
    }
    render();
    await runCheck();
  }

  function renderRoster(list) {
    $("roster-list").innerHTML = list.map((c) =>
      `<button class="item${c.id === App.selected ? " on" : ""}" data-id="${esc(c.id)}">${esc(c.name)}` +
      `<small>${c.age ?? "?"} · ${esc(c.id)}${c.errors.length ? ' · <span class="bad">errors</span>' : ""}</small></button>`).join("");
    $("roster-list").querySelectorAll(".item").forEach((b) => (b.onclick = () => App.select(b.dataset.id)));
  }

  async function createFrom(data, label) {
    try {
      const made = await App.api("POST", "/api/characters", data);
      saved = draft = null;   // nothing unsaved to protect now
      await App.loadCharacters(made.id);
      App.toast(`${label} ${made.name}`);
    } catch (e) {
      alert(e.message + (e.errors.length ? "\n\n" + e.errors.join("\n") : ""));
    }
  }

  $("save").onclick = async () => {
    try {
      await App.api("PUT", `/api/characters/${encodeURIComponent(id)}`, draft);
      saved = structuredClone(draft);
      const keep = id;
      await App.loadCharacters(keep);
      paintStatus();
      App.toast("Saved");
    } catch (e) {
      check = { errors: e.errors.length ? e.errors : [e.message], warnings: check.warnings };
      paintStatus();
    }
  };
  $("revert").onclick = () => { draft = structuredClone(saved); render(); runCheck(); };
  $("duplicate").onclick = () => {
    if (!draft) return;
    const copy = structuredClone(draft);
    const name = prompt("Name for the copy", `${copy.scenario.patient_name} (copy)`);
    if (!name) return;
    copy.scenario.patient_name = name;
    createFrom(copy, "Created");
  };
  $("new-char").onclick = () => {
    if (!App.guards.every((g) => g(null))) return;
    const name = prompt("Patient name");
    if (!name) return;
    // Starts from the selected character so every field has a sensible value.
    const base = structuredClone(saved || draft);
    base.scenario = { patient_name: name, age: base.scenario.age, prompt: "" };
    base.voice = { ...(base.voice || {}), voice_id: "" };
    createFrom(base, "Created");
  };
  $("export").onclick = () => {
    if (!draft) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2) + "\n"], { type: "application/json" }));
    a.download = `${id || "character"}.json`;
    a.click();
  };
  $("import-char").onclick = () => $("import-file").click();
  $("import-file").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try { await createFrom(JSON.parse(await file.text()), "Imported"); }
    catch (err) { alert("Not a JSON file: " + err.message); }
  };
  $("delete").onclick = async () => {
    if (!id || !confirm(`Delete ${draft?.scenario?.patient_name || id}? The file moves to the deleted/ folder.`)) return;
    try {
      await App.api("DELETE", `/api/characters/${encodeURIComponent(id)}`);
      saved = draft = null;
      App.selected = null;
      await App.loadCharacters();
      App.toast("Deleted");
    } catch (e) { alert(e.message); }
  };
  $("talk").onclick = () => {
    if (dirty() && !confirm("Unsaved changes will not be in the session. Talk to the saved version?")) return;
    location.hash = "#session";
  };

  // Do not lose edits when switching character or closing the tab.
  App.guards.push(() => !dirty() || confirm("Discard unsaved changes to this character?"));
  window.addEventListener("beforeunload", (e) => { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });

  App.listeners.config.push(async () => {
    try { DEFAULTS = await App.api("GET", "/api/defaults"); } catch (e) { DEFAULTS = {}; }
    if (draft) render();
  });

  App.listeners.list.push(renderRoster);
  App.listeners.select.push((charId) => { renderRoster(App.characters); load(charId); });

  return { dirty };
})();
