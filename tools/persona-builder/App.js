function App() {
  const { useState, useMemo } = React;

  const [name, setName] = useState("Layla Haddad");
  const [trust, setTrust] = useState(TRUST_OPTIONS[2]);
  const [saturation, setSaturation] = useState(SATURATION_OPTIONS[1]);
  const [primaryEmotion, setPrimaryEmotion] = useState("SHOCK");
  const [secondaryEmotion, setSecondaryEmotion] = useState("GRIEF");
  const [blend, setBlend] = useState(BLEND_OPTIONS[0]);
  const [intensity, setIntensity] = useState(INTENSITY_OPTIONS[1]);
  const [defenseMode, setDefenseMode] = useState("SARCASM");
  const [defenseTrigger, setDefenseTrigger] = useState(DEFENSE_TRIGGER_OPTIONS[1]);
  const [validationRelief, setValidationRelief] = useState(RELIEF_OPTIONS[1]);
  const [silence, setSilence] = useState(SILENCE_OPTIONS[1]);
  const [reassurance, setReassurance] = useState(SEVERITY_OPTIONS[1]);
  const [jargon, setJargon] = useState(SEVERITY_OPTIONS[1]);
  const [logistics, setLogistics] = useState(SEVERITY_OPTIONS[1]);
  const [interruption, setInterruption] = useState(SEVERITY_OPTIONS[2]);
  const [patience, setPatience] = useState(3);
  const [escalationSeverity, setEscalationSeverity] = useState(ESCALATION_SEVERITY[1]);

  const state = { trust, saturation, primaryEmotion, secondaryEmotion, blend, intensity, defenseMode, defenseTrigger, validationRelief, silence, reassurance, jargon, logistics, interruption, patience, escalationSeverity };
  const tuning = useMemo(() => buildTuning(state), Object.values(state));

  return (
    <div className="min-h-screen bg-white text-black font-mono">
      <div className="border-b-2 border-black px-6 py-5">
        <div className="text-[11px] uppercase tracking-widest text-zinc-500 mb-1">Cluster Avatar Project</div>
        <h1 className="text-3xl font-bold tracking-tighter">Persona Builder</h1>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-3 border-2 border-black px-3 py-2 text-sm w-full max-w-xs focus:outline-none"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_420px]">
        <div className="px-6 py-6 lg:border-r-2 border-black">
          <StartingPointSection trust={trust} setTrust={setTrust} saturation={saturation} setSaturation={setSaturation} primaryEmotion={primaryEmotion} setPrimaryEmotion={setPrimaryEmotion} secondaryEmotion={secondaryEmotion} setSecondaryEmotion={setSecondaryEmotion} blend={blend} setBlend={setBlend} intensity={intensity} setIntensity={setIntensity} />
          <DefenseSection defenseMode={defenseMode} setDefenseMode={setDefenseMode} defenseTrigger={defenseTrigger} setDefenseTrigger={setDefenseTrigger} />
          <ReactionsSection validationRelief={validationRelief} setValidationRelief={setValidationRelief} silence={silence} setSilence={setSilence} reassurance={reassurance} setReassurance={setReassurance} jargon={jargon} setJargon={setJargon} logistics={logistics} setLogistics={setLogistics} interruption={interruption} setInterruption={setInterruption} />
          <EscalationSection patience={patience} setPatience={setPatience} escalationSeverity={escalationSeverity} setEscalationSeverity={setEscalationSeverity} />
        </div>

        <div className="px-6 py-6 bg-zinc-50">
          <div className="text-xs uppercase tracking-widest text-zinc-500 mb-3">Summary</div>
          <SummaryTable rows={[
            ["Trust", trust.label],
            ["Saturation", saturation.label],
            ["Emotion", `${primaryEmotion} / ${secondaryEmotion}`],
            ["Blend", blend.label],
            ["Intensity", intensity.label],
            ["Defense", defenseMode],
            ["Guardedness", defenseTrigger.label],
            ["Patience", `${patience} turns`],
            ["Escalation", escalationSeverity.label],
          ]} />
          <button
            onClick={() => downloadJson(tuning, `${name.trim().toLowerCase().replace(/\s+/g, "_") || "patient"}.tuning.json`)}
            className="w-full bg-black text-white py-3 text-xs uppercase tracking-widest shadow-[2px_2px_0px_0px_#000] hover:shadow-none hover:translate-x-[2px] hover:translate-y-[2px] transition-all"
          >
            Export tuning.json
          </button>
        </div>
      </div>
    </div>
  );
}