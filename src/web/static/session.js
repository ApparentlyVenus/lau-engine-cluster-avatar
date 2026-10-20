// Session view: mic in, her voice out, live transcript and state.
const Session = (() => {
  const IN_RATE = 16000, OUT_RATE = 24000;
  let sttEmpty = 0;
  let ws, micCtx, micStream, playCtx, nextTime = 0, sources = [], liveP = null, partialEl = null, lastLearner = null;

  // ---- who we are talking to ---------------------------------------------
  function showWho() {
    const c = App.current();
    $("who").textContent = c ? c.name : "";
    $("who-sub").textContent = c ? (c.age ? `, ${c.age}` : "") + (c.errors.length ? " · this character has errors, fix them in Characters" : "") : "";
  }
  App.listeners.select.push(showWho);
  App.listeners.list.push(showWho);
  App.guards.push(() => {
    if (!ws) return true;
    alert("End the current session before switching patient.");
    return false;
  });

  // ---- conversation log -----------------------------------------------------
  const fmtLearner = (s) => esc(s).replace(/\[pause ([\d.]+)s\]/g, '<span class="pause">pause $1s</span>');
  const fmtPatient = (s) => esc(s).replace(/\[([^\]]+)\]/g, '<span class="tag">[$1]</span>');
  function addTurn(html) {
    const log = $("log");
    if (log.querySelector(".empty")) log.innerHTML = "";
    const div = document.createElement("div");
    div.className = "turn"; div.innerHTML = html;
    log.appendChild(div); log.scrollTop = log.scrollHeight;
    return div;
  }

  function onEvent(ev) {
    switch (ev.type) {
      case "learner_partial":
        if (!partialEl) partialEl = addTurn('<div class="who-l">Doctor</div><div class="partial"></div>');
        partialEl.querySelector(".partial").textContent = ev.text;
        $("log").scrollTop = $("log").scrollHeight;
        break;
      case "learner_final": {
        const el = partialEl || addTurn("");
        partialEl = null;
        el.innerHTML = '<div class="who-l">Doctor</div><div>' + fmtLearner(ev.annotated || ev.text) + "</div>" +
          (ev.timing ? '<div class="timing">' + esc(ev.timing) + "</div>" : "");
        lastLearner = el;
        break;
      }
      case "turn_reopened":
        // The doctor was only pausing: drop the half turn (and any reply to it);
        // it comes back merged with what follows.
        if (lastLearner) {
          while (lastLearner.nextSibling) lastLearner.nextSibling.remove();
          lastLearner.remove();
          lastLearner = null;
        }
        liveP = null;
        break;
      case "patient_interjects":
        addTurn('<div class="who-p">Patient (interrupts)</div><div>' + fmtPatient(ev.text) + "</div>");
        break;
      case "patient_chunk": {
        if (!liveP) liveP = addTurn('<div class="who-p">Patient</div><div class="txt"></div>');
        const txt = liveP.querySelector(".txt");
        txt.innerHTML += (txt.innerHTML ? " " : "") + fmtPatient(ev.text);
        $("log").scrollTop = $("log").scrollHeight;
        break;
      }
      case "patient_done":
        if (liveP && ev.note) liveP.insertAdjacentHTML("beforeend", '<div class="note">' + esc(ev.note) + "</div>");
        liveP = null;
        break;
      case "network":
        addTurn('<div class="cut">Slow connection: your words reached the transcriber ' + ev.stt_lag_s +
                "s after you stopped (normally ~0.5s). Turn-taking will feel off until it recovers.</div>");
        break;
      case "stt_empty":
        sttEmpty += 1;
        addTurn('<div class="cut">Heard you, but speech-to-text returned no words' +
                (sttEmpty > 1 ? ` (${sttEmpty} times now). Riva may be down: run <code>python src/tools/riva_check.py</code>.` : ".") + "</div>");
        break;
      case "out_of_character":
        addTurn('<div class="cut">The model broke character here; a fallback line was spoken instead. Logged.</div>');
        break;
      case "cut_off":
        if (liveP) liveP.insertAdjacentHTML("beforeend", '<div class="cut">cut off by the doctor</div>');
        liveP = null;
        break;
      case "error":
        addTurn('<div class="cut">Could not start: ' + esc(ev.message) + "</div>");
        break;
      case "state": showState(ev); break;
      case "latency": showLatency(ev); break;
      case "clear": stopPlayback(); break;
    }
  }

  function showState(s) {
    $("emotion").textContent = s.emotion;
    $("undertone").textContent = `undertone ${s.undertone} · intensity ${s.intensity}`;
    $("trust").textContent = `${s.trust} ${s.trust_band}`;
    $("sat").textContent = `${s.saturation} ${s.saturation_band}`;
    $("trustbar").firstElementChild.style.width = (s.trust * 100) + "%";
    $("satbar").firstElementChild.style.width = (s.saturation * 100) + "%";
    $("defense").textContent = s.defense;
    $("unack").textContent = s.unacknowledged;
    const flags = Object.entries(s.flags || {});
    if (s.flags) $("flags").innerHTML = flags.length
      ? flags.map(([k, v]) => `<span>${esc(k)} ${(+v).toFixed(2)}</span>`).join("") + (s.escalated ? "<span>escalated</span>" : "")
      : '<span class="empty">no behaviours flagged</span>';
  }

  function resetPanels() {
    for (const id of ["emotion", "trust", "sat", "defense", "unack"]) $(id).textContent = "–";
    $("undertone").textContent = "";
    $("trustbar").firstElementChild.style.width = $("satbar").firstElementChild.style.width = "0";
    $("flags").innerHTML = '<span class="empty">none yet</span>';
    $("lat").innerHTML = '<span class="empty">none yet</span>';
  }

  function showLatency(l) {
    const rows = [["turn end", l.final], ["interpreter", l.interp_done], ["first chunk", l.first_chunk], ["first audio", l.first_audio]]
      .filter(([, v]) => v !== undefined).map(([k, v]) => `${k.padEnd(12, " ")} ${v.toFixed(2)}s`);
    $("lat").innerHTML = rows.length ? "<pre style='margin:0'>" + rows.join("\n") + "</pre>" : '<span class="empty">–</span>';
  }

  // ---- her voice ------------------------------------------------------------
  function play(buf) {
    const pcm = new Int16Array(buf);
    if (!pcm.length) return;
    const f = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 32768;
    const ab = playCtx.createBuffer(1, f.length, OUT_RATE);
    ab.copyToChannel(f, 0);
    const src = playCtx.createBufferSource();
    src.buffer = ab; src.connect(playCtx.destination);
    const start = Math.max(playCtx.currentTime + 0.03, nextTime);
    src.start(start); nextTime = start + ab.duration;
    sources.push(src);
    $("dot").className = "dot speaking";
    src.onended = () => {
      sources = sources.filter((s) => s !== src);
      if (!sources.length) $("dot").className = ws ? "dot live" : "dot";
    };
  }
  function stopPlayback() {
    sources.forEach((s) => { try { s.stop(); } catch (e) {} });
    sources = []; nextTime = 0;
    $("dot").className = ws ? "dot live" : "dot";
  }

  // ---- mic ------------------------------------------------------------------
  const WORKLET = `
  class Capture extends AudioWorkletProcessor {
    constructor() { super(); this.ratio = sampleRate / ${IN_RATE}; this.pos = 0; this.sum = 0; this.n = 0;
                    this.out = []; this.lvl = 0; this.frames = 0; }
    process(inputs) {
      const ch = inputs[0][0];
      if (!ch) return true;
      for (let i = 0; i < ch.length; i++) {
        // box-filter downsample to 16 kHz
        this.sum += ch[i]; this.n++; this.pos += 1;
        if (this.pos >= this.ratio) { this.pos -= this.ratio; this.out.push(this.sum / this.n); this.sum = 0; this.n = 0; }
        this.lvl = Math.max(this.lvl * 0.9995, Math.abs(ch[i]));
      }
      if (this.out.length >= 320) {             // 20 ms chunks
        const pcm = new Int16Array(this.out.length);
        for (let i = 0; i < this.out.length; i++) pcm[i] = Math.max(-1, Math.min(1, this.out[i])) * 32767;
        this.out = [];
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
      }
      if (++this.frames % 8 === 0) this.port.postMessage({ level: this.lvl });
      return true;
    }
  }
  registerProcessor("capture", Capture);`;

  async function start() {
    if (!App.selected) throw new Error("No patient selected");
    $("log").innerHTML = "";
    sttEmpty = 0;
    resetPanels();
    playCtx = new AudioContext({ sampleRate: OUT_RATE });
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    micCtx = new AudioContext();
    await micCtx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    const node = new AudioWorkletNode(micCtx, "capture");
    micCtx.createMediaStreamSource(micStream).connect(node);

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const q = new URLSearchParams({ barge_in: $("barge").checked ? "1" : "0", character: App.selected });
    ws = new WebSocket(`${proto}://${location.host}/ws?${q}`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => { $("dot").className = "dot live"; };
    ws.onmessage = (m) => (typeof m.data === "string" ? onEvent(JSON.parse(m.data)) : play(m.data));
    ws.onclose = () => { stop(); };
    node.port.onmessage = (e) => {
      if (e.data.level !== undefined) { $("level").style.width = Math.min(100, e.data.level * 250) + "%"; return; }
      if (ws && ws.readyState === 1) ws.send(e.data);
    };
    $("go").textContent = "End"; $("go").className = "stop";
    $("barge").disabled = $("character").disabled = true;
  }

  function stop() {
    if (ws) { const w = ws; ws = null; try { w.close(); } catch (e) {} }
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    if (micCtx) micCtx.close();
    stopPlayback();
    micStream = micCtx = null;
    $("go").textContent = "Start"; $("go").className = "";
    $("barge").disabled = $("character").disabled = false;
    $("dot").className = "dot"; $("level").style.width = "0";
  }

  $("go").onclick = () => (ws ? stop() : start().catch((e) => { alert("Could not start: " + e.message); stop(); }));
  App.listeners.config.push((c) => { $("barge").checked = c.barge_in; });

  return { live: () => !!ws };
})();
