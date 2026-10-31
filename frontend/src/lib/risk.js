// Risk levels in order of severity. Colors were checked with a palette validator:
// neighbouring levels stay distinguishable with normal and colour-blind vision.
// Colour never carries meaning alone: markers also grow with severity, and every
// level is labelled in text (tooltip, legend, table).
export const RISK_LEVELS = [
  { label: 'Low', color: '#0ca30c', radius: 5 },
  { label: 'Moderate', color: '#ffd23f', radius: 6 },
  { label: 'High', color: '#e8771a', radius: 7 },
  { label: 'Severe', color: '#a81f2c', radius: 8 },
  { label: 'No Travel', color: '#4a1a5c', radius: 9 },
]

const BY_LABEL = Object.fromEntries(RISK_LEVELS.map((level) => [level.label, level]))

export const riskStyle = (label) => BY_LABEL[label] ?? RISK_LEVELS[0]

export function milesByLevel(route) {
  const miles = Object.fromEntries(RISK_LEVELS.map((level) => [level.label, 0]))
  for (const cp of route.checkpoints) miles[cp.risk.level] += cp.covered_miles
  return RISK_LEVELS.map((level) => ({ ...level, miles: miles[level.label] }))
}

export const ROUTE_COLORS = {
  A: '#2a78d6', // Vibrant Blue
  B: '#8b5cf6', // Violet / Purple
  C: '#0d9488', // Emerald Teal
}
