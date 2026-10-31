import { RISK_LEVELS } from '../lib/risk'

export default function RiskLegend() {
  return (
    <div className="risk-legend" aria-label="Risk levels">
      {RISK_LEVELS.map((level) => (
        <span key={level.label} className="legend-item">
          <svg width="22" height="22" aria-hidden="true">
            <circle cx="11" cy="11" r={level.radius} fill={level.color} strokeWidth="1.5" />
          </svg>
          {level.label}
        </span>
      ))}
    </div>
  )
}
