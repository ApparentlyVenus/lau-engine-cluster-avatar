const TRUST_OPTIONS = [
  { label: "Shut down", value: 0.10 },
  { label: "Distrustful", value: 0.32 },
  { label: "Guarded", value: 0.57 },
  { label: "Trusting", value: 0.85 },
];

const SATURATION_OPTIONS = [
  { label: "Calm", value: 0.15 },
  { label: "Strained", value: 0.45 },
  { label: "Overwhelmed", value: 0.72 },
  { label: "Breaking point", value: 0.93 },
];

const SEVERITY_OPTIONS = [
  { label: "Mild", trust: -0.03, sat: 0.04 },
  { label: "Moderate", trust: -0.06, sat: 0.08 },
  { label: "Severe", trust: -0.10, sat: 0.14 },
];

const RELIEF_OPTIONS = [
  { label: "Low", trust: 0.05, sat: -0.03 },
  { label: "Medium", trust: 0.10, sat: -0.08 },
  { label: "High", trust: 0.16, sat: -0.13 },
];

const SILENCE_OPTIONS = [
  { label: "Dislikes silence", trust: -0.04, sat: 0.03 },
  { label: "Neutral", trust: 0.0, sat: 0.0 },
  { label: "Appreciates silence", trust: 0.05, sat: -0.04 },
];

const ESCALATION_SEVERITY = [
  { label: "Mild", trust: -0.03, sat: 0.08 },
  { label: "Moderate", trust: -0.05, sat: 0.15 },
  { label: "Severe", trust: -0.08, sat: 0.22 },
];

const BLEND_OPTIONS = [
  { label: "Subtle undertone", value: 0.1 },
  { label: "Balanced blend", value: 0.3 },
  { label: "Strong undertone", value: 0.5 },
];

const INTENSITY_OPTIONS = [
  { label: "Mild", value: 0.4 },
  { label: "Moderate", value: 0.65 },
  { label: "Intense", value: 0.9 },
];

const DEFENSE_TRIGGER_OPTIONS = [
  { label: "Guards herself quickly", value: 0.45 },
  { label: "Guards herself normally", value: 0.35 },
  { label: "Rarely gets defensive", value: 0.20 },
];

const PATIENCE_OPTIONS = [1, 2, 3, 4, 5, 6];
const DEFENSE_MODES = ["SARCASM", "INTELLECTUALIZING", "MINIMIZING"];
const EMOTIONS = ["SHOCK", "ANGER", "GRIEF", "FEAR", "BARGAINING"];