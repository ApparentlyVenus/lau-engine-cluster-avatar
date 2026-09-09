function StartingPointSection({ trust, setTrust, saturation, setSaturation, primaryEmotion, setPrimaryEmotion, secondaryEmotion, setSecondaryEmotion, blend, setBlend, intensity, setIntensity }) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-widest text-zinc-500 border-b border-zinc-300 pb-1">Starting point</div>
      <NumberDial label="Starting trust" options={TRUST_OPTIONS} value={trust} onChange={setTrust} />
      <NumberDial label="Starting saturation" options={SATURATION_OPTIONS} value={saturation} onChange={setSaturation} />
      <div className="grid grid-cols-2 gap-6">
        <SegmentedControl label="Primary emotion" options={EMOTIONS} value={primaryEmotion} onChange={setPrimaryEmotion} getLabel={(o) => o} getKey={(o) => o} />
        <SegmentedControl label="Secondary emotion" options={EMOTIONS} value={secondaryEmotion} onChange={setSecondaryEmotion} getLabel={(o) => o} getKey={(o) => o} />
      </div>
      <NumberDial label="Blend strength" help="How much the secondary emotion bleeds into the primary." options={BLEND_OPTIONS} value={blend} onChange={setBlend} />
      <NumberDial label="Emotional intensity" help="Overall strength of the starting emotion." options={INTENSITY_OPTIONS} value={intensity} onChange={setIntensity} />
    </div>
  );
}

function DefenseSection({ defenseMode, setDefenseMode, defenseTrigger, setDefenseTrigger }) {
  return (
    <div>
      <div className="mb-2 mt-4 text-xs uppercase tracking-widest text-zinc-500 border-b border-zinc-300 pb-1">Defense</div>
      <SegmentedControl label="Preferred defense" help="What she reaches for once she starts guarding herself." options={DEFENSE_MODES} value={defenseMode} onChange={setDefenseMode} getLabel={(o) => o} getKey={(o) => o} />
      <NumberDial label="Guardedness" help="How easily her defense activates." options={DEFENSE_TRIGGER_OPTIONS} value={defenseTrigger} onChange={setDefenseTrigger} />
    </div>
  );
}

function ReactionsSection({ validationRelief, setValidationRelief, silence, setSilence, reassurance, setReassurance, jargon, setJargon, logistics, setLogistics, interruption, setInterruption }) {
  return (
    <div>
      <div className="mb-2 mt-4 text-xs uppercase tracking-widest text-zinc-500 border-b border-zinc-300 pb-1">How she reacts</div>
      <SegmentedControl label="Relief from validation" options={RELIEF_OPTIONS} value={validationRelief} onChange={setValidationRelief} />
      <SegmentedControl label="Reaction to silence" options={SILENCE_OPTIONS} value={silence} onChange={setSilence} />
      <SegmentedControl label="Reaction to premature reassurance" options={SEVERITY_OPTIONS} value={reassurance} onChange={setReassurance} />
      <SegmentedControl label="Reaction to jargon" options={SEVERITY_OPTIONS} value={jargon} onChange={setJargon} />
      <SegmentedControl label="Reaction to logistics-first" options={SEVERITY_OPTIONS} value={logistics} onChange={setLogistics} />
      <SegmentedControl label="Reaction to being interrupted" options={SEVERITY_OPTIONS} value={interruption} onChange={setInterruption} />
    </div>
  );
}

function EscalationSection({ patience, setPatience, escalationSeverity, setEscalationSeverity }) {
  return (
    <div>
      <div className="mb-2 mt-4 text-xs uppercase tracking-widest text-zinc-500 border-b border-zinc-300 pb-1">Escalation</div>
      <NumberDial label="Patience" help="Turns before being ignored forces an escalation." options={PATIENCE_OPTIONS} value={patience} onChange={setPatience} suffix=" turns" />
      <SegmentedControl label="Escalation severity" options={ESCALATION_SEVERITY} value={escalationSeverity} onChange={setEscalationSeverity} />
    </div>
  );
}