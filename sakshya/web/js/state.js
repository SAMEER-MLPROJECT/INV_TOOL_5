const listeners = new Set();

export const state = {
  caseId: null,
  bundle: null,
  view: "overview",
  asOf: null,
  policy: "pro_rata",
};

export function setState(patch) {
  Object.assign(state, patch);
  for (const listener of listeners) listener(state, patch);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function hypothesisById(id) {
  return (state.bundle?.hypotheses || []).find((h) => h.id === id) || null;
}

export function crimeHypothesis() {
  const bundle = state.bundle;
  if (!bundle) return null;
  const label = bundle.decision.label;
  return (
    bundle.hypotheses.find((h) => h.template === label) || bundle.hypotheses.find((h) => h.template !== "no_offence") || null
  );
}

export function personById(id) {
  return (state.bundle?.people || []).find((p) => p.id === id) || null;
}

export function personOf(entity) {
  return (state.bundle?.people || []).find((p) => p.members.some((m) => m.entity === entity)) || null;
}
