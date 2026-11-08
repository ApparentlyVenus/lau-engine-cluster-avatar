// Turn log: every scored turn of the sessions in this tab, with the state
// before and after and what moved it. For diagnostics; nothing is stored.
const TurnLog = (() => {
  const sessions = [];        // { character, started, turns: [...] }
  let current = null, lastTurn = null, sinceFinal = false, replyText = "";

  const NUM = [
    ["trust", "Trust"], ["saturation", "Saturation"], ["competence", "Rates the doctor"],
    ["shock", "Shock"], ["blame", "Blame"], ["intensity", "Intensity"],
  ];
  const COUNT = [["unacknowledged", "Unacknowledged turns"], ["unanswered", "Unanswered questions"]];
  const TEXT = [["emotion", "Emotion"], ["undertone", "Undertone"], ["defense", "Defense"]];
  const pretty = (s) => String(s).replace(/_/g, " ");
  const sign = (v) => (!v ? "" : (v > 0 ? "+" : "−") + String(Math.round(Math.abs(v) * 1000) / 1000));
  const cls = (v, goodUp) => (v === 0 ? "" : (v > 0) === goodUp ? "up" : "down");

  function newSession(character) {
    current = { character, started: new Date().toISOString(), turns: [] };
    sessions.push(current);
    lastTurn = null; sinceFinal = false; replyText = "";
    render();
  }

  function onEvent(ev) {
    if (!current) newSession(App.current()?.name || "?");
    switch (ev.type) {
      case "learner_final":
        sinceFinal = false; replyText = "";
        break;
      case "state":
        lastTurn = {
          n: current.turns.length + 1, turn_id: ev.turn_id, transcript: ev.transcript, before: ev.before,
          after: pick(ev), flags: ev.flags || {}, trace: ev.trace || {}, escalated: ev.escalated, reply: "",
        };
        current.turns.push(lastTurn);
        sinceFinal = true;
        render();
        break;
      case "patient_chunk":
        replyText += (replyText ? " " : "") + ev.text;
        if (lastTurn && sinceFinal) { lastTurn.reply = replyText; renderLast(); }
        break;
      case "patient_done":
        replyText = "";
        break;
      case "turn_reopened":
        // The doctor was only pausing: that turn was undone and comes back merged.
        if (lastTurn && sinceFinal) { lastTurn.rolledBack = true; render(); }
        break;
    }
  }

  function pick(ev) {
    const out = {};
    for (const k of ["trust", "saturation", "competence", "shock", "blame", "intensity", "unacknowledged", "unanswered",
                     "emotion", "undertone", "defense", "news_delivered", "satisfaction", "ended", "trust_band", "saturation_band"]) out[k] = ev[k];
    return out;
  }

  // ---- rendering ---------------------------------------------------------------
  function render() {
    const box = $("turnlog");
    if (!box) return;
    const all = sessions.filter((s) => s.turns.length);
    $("tl-count").textContent = all.length ? ` · ${all.reduce((n, s) => n + s.turns.length, 0)} turns` : "";
    if (!all.length) { box.innerHTML = '<p class="empty">No turns yet. Start a session; every scored turn shows up here with what changed and why.</p>'; return; }
    box.innerHTML = all.map((s) =>
      `<div class="tl-session">${esc(s.character)} · started ${new Date(s.started).toLocaleTimeString()}</div>` +
      s.turns.map(turnHtml).join("")).join("");
  }

  function renderLast() {
    const el = document.querySelector(`.tl-turn[data-key="${keyOf(lastTurn)}"] .tl-reply`);
    if (el) el.textContent = lastTurn.reply;
  }

  const keyOf = (t) => `${sessions.indexOf(current)}-${t.n}`;

  function turnHtml(t) {
    const b = t.before || {}, a = t.after, tr = t.trace;
    const rows = [];
    for (const [k, label] of NUM) {
      if (b[k] === undefined || a[k] === undefined) continue;
      const d = Math.round((a[k] - b[k]) * 1000) / 1000;
      const goodUp = !["saturation", "shock", "blame"].includes(k);
      rows.push(`<tr><td>${label}</td><td>${(+b[k]).toFixed(2)}</td><td>${(+a[k]).toFixed(2)}</td><td class="${k === "intensity" ? "" : cls(d, goodUp)}">${d ? sign(d) : ""}</td></tr>`);
    }
    for (const [k, label] of COUNT) {
      if (b[k] === undefined) continue;
      rows.push(`<tr><td>${label}</td><td>${b[k]}</td><td>${a[k]}</td><td>${a[k] !== b[k] ? (a[k] > b[k] ? "+" : "−") + Math.abs(a[k] - b[k]) : ""}</td></tr>`);
    }
    for (const [k, label] of TEXT) {
      if (b[k] === undefined) continue;
      rows.push(`<tr><td>${label}</td><td>${esc(pretty(b[k]).toLowerCase())}</td><td>${esc(pretty(a[k]).toLowerCase())}</td><td>${a[k] !== b[k] ? "changed" : ""}</td></tr>`);
    }

    const why = [];
    for (const f of tr.flags || []) {
      why.push(`<tr><td>${esc(pretty(f.flag))}</td><td>${f.intensity}</td><td>${f.multiplier !== 1 ? "×" + f.multiplier : ""}</td>` +
        `<td class="${cls(f.trust, true)}">${sign(f.trust)}</td><td class="${cls(f.saturation, false)}">${sign(f.saturation)}</td><td>${f.acknowledges ? "acknowledges" : ""}</td></tr>`);
    }
    const ev = (name, o) => o && why.push(`<tr class="ev"><td>${name}</td><td></td><td></td><td class="${cls(o.trust, true)}">${sign(o.trust)}</td><td class="${cls(o.saturation, false)}">${sign(o.saturation)}</td><td></td></tr>`);
    ev("the news", tr.disclosure);
    ev("unanswered question", tr.frustration);
    ev("patience ran out", tr.escalation);

    const notes = [];
    if (tr.reacting_in) notes.push(`Reacting while in: ${tr.reacting_in.map((s) => pretty(s).toLowerCase()).join(" + ")}`);
    if (tr.she_asked) notes.push(`Patient had asked a question: ${tr.answered ? "answered" : "not answered"}`);
    if (tr.competence && Object.keys(tr.competence).length)
      notes.push("Rates the doctor: " + Object.entries(tr.competence).map(([k, v]) => `${pretty(k)} ${sign(v)}`).join(", "));
    if (tr.blame && (tr.blame.added || tr.blame.removed || tr.blame.faded))
      notes.push("Blame: " + [["added", tr.blame.added], ["removed", tr.blame.removed], ["faded", tr.blame.faded]].filter(([, v]) => v).map(([k, v]) => `${k} ${sign(v)}`).join(", "));
    if (tr.shock) notes.push(`Shock: fades ${tr.shock.decay}${tr.shock.relief ? `, faster by ${tr.shock.relief}` : ""}${tr.shock.prolong ? `, slower by ${tr.shock.prolong}` : ""}`);
    if (tr.emotion_scores) notes.push("Emotion scores: " + Object.entries(tr.emotion_scores).map(([k, v]) => `${k.toLowerCase()} ${v.toFixed(2)}`).join(", "));
    if (tr.walkout) notes.push("Trust stayed too low: the patient walks out.");
    if (tr.skipped) notes.push(tr.skipped);

    const answers = (t.flags.answers_question || 0) >= 0.5 ? '<span>answers question</span>' : "";
    const news = (t.flags.discloses_news || 0) >= 0.5 ? '<span>discloses news</span>' : "";
    return `<div class="tl-turn${t.rolledBack ? " rolled" : ""}" data-key="${keyOf(t)}">
      <div class="tl-head"><b>Turn ${t.n}</b>${t.rolledBack ? '<span class="tl-tag">undone, merged into the next turn</span>' : ""}${t.escalated ? '<span class="tl-tag bad">escalated</span>' : ""}</div>
      <div class="tl-line"><span class="who-l">Doctor</span> ${esc(t.transcript || "")}</div>
      <div class="tl-line"><span class="who-p">Patient</span> <span class="tl-reply">${esc(t.reply || "")}</span></div>
      <div class="tl-grid">
        <table class="tl-state"><thead><tr><th></th><th>before</th><th>after</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table>
        <div>
          ${why.length || answers || news ? `<table class="tl-why"><thead><tr><th>what moved it</th><th>strength</th><th>state</th><th>trust</th><th>saturation</th><th></th></tr></thead><tbody>${why.join("")}</tbody></table>` : '<p class="sub">No behaviours flagged.</p>'}
          ${answers || news ? `<div class="chips">${answers}${news}</div>` : ""}
          <ul class="tl-notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
        </div>
      </div>
    </div>`;
  }

  // ---- buttons ---------------------------------------------------------------
  window.addEventListener("DOMContentLoaded", () => {
    $("tl-clear").onclick = () => { sessions.length = 0; current = null; lastTurn = null; render(); };
    $("tl-download").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(sessions, null, 2) + "\n"], { type: "application/json" }));
      a.download = `turn-log-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.json`;
      a.click();
    };
    render();
  });

  return { onEvent, newSession, render };
})();
