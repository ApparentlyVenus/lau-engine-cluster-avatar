function buildTuning(state) {
  return {
    severity_scale: {
      trust_bands: {
        trusting: { min: 0.70, max: 1.00 },
        guarded: { min: 0.45, max: 0.69 },
        distrustful: { min: 0.20, max: 0.44 },
        shut_down: { min: 0.00, max: 0.19 },
      },
      saturation_bands: {
        calm: { min: 0.00, max: 0.29 },
        strained: { min: 0.30, max: 0.59 },
        overwhelmed: { min: 0.60, max: 0.84 },
        breaking_point: { min: 0.85, max: 1.00 },
      },
    },
    personality: {
      preferred_defense_mode: state.defenseMode,
      acknowledgment_intensity_threshold: 0.3,
      unacknowledged_threshold: state.patience,
      trust_penalty: state.escalationSeverity.trust,
      saturation_penalty: state.escalationSeverity.sat,
      defense_trigger_trust: state.defenseTrigger.value,
    },
    initial_state: {
      trust: state.trust.value,
      saturation: state.saturation.value,
      emotion: {
        primary: state.primaryEmotion,
        secondary: state.secondaryEmotion,
        blend_weight: state.blend.value,
        intensity: state.intensity.value,
      },
      defense: { mode: "NONE", masking: "NONE" },
    },
    flag_deltas: {
      validating: { trust: state.validationRelief.trust, saturation: state.validationRelief.sat, acknowledges: true },
      silence_tolerance: { trust: state.silence.trust, saturation: state.silence.sat, acknowledges: true },
      premature_reassurance: { trust: state.reassurance.trust, saturation: state.reassurance.sat, acknowledges: false },
      jargon: { trust: state.jargon.trust, saturation: state.jargon.sat, acknowledges: false },
      logistics_first: { trust: state.logistics.trust, saturation: state.logistics.sat, acknowledges: false },
      interruption: { trust: state.interruption.trust, saturation: state.interruption.sat, acknowledges: false },
    },
  };
}

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}