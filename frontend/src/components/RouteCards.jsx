import { formatDuration, formatMiles } from '../lib/format'
import { ROUTE_COLORS, milesByLevel } from '../lib/risk'

function RiskStrip({ route }) {
  const levels = milesByLevel(route).filter((level) => level.miles > 0)
  const total = levels.reduce((sum, level) => sum + level.miles, 0)
  return (
    <div className="risk-strip" role="img" aria-label={levels.map((l) => `${l.label} ${Math.round(l.miles)} miles`).join(', ')}>
      {levels.map((level) => (
        <span
          key={level.label}
          style={{ flexGrow: level.miles / total, background: level.color }}
          title={`${level.label}: ${formatMiles(level.miles)}`}
        />
      ))}
    </div>
  )
}

function RouteCard({ route, recommended, reason, selected, onSelect }) {
  const levels = milesByLevel(route)
  const lowMiles = levels.find((l) => l.label === 'Low')?.miles ?? 0
  const isAllClear = route.no_travel_miles === 0 && route.severe_miles === 0 && route.high_miles === 0
  const routeColor = ROUTE_COLORS[route.id] || '#2a78d6'

  return (
    <button
      type="button"
      className={`route-card${selected ? ' selected' : ''}`}
      aria-pressed={selected}
      onClick={() => onSelect(route.id)}
    >
      <div className="route-card-head">
        <span
          className="route-color-pill"
          style={{ backgroundColor: routeColor }}
          title={`Route ${route.id} map color`}
        />
        <strong>Route {route.id}</strong>
        {recommended && <span className="badge">Recommended</span>}
        {route.is_detour && <span className="tag">via detour</span>}
      </div>
      <div className="route-card-stats">
        <span>{formatMiles(route.distance_miles)}</span>
        <span>{formatDuration(route.duration_s)}</span>
        <span>avg risk {route.avg_risk.toFixed(2)}</span>
      </div>
      <RiskStrip route={route} />
      <dl className="route-card-miles">
        <div className="stat-low"><dt>Low (Safe)</dt><dd>{formatMiles(lowMiles)}</dd></div>
        <div><dt>High</dt><dd>{formatMiles(route.high_miles)}</dd></div>
        <div><dt>Severe</dt><dd>{formatMiles(route.severe_miles)}</dd></div>
        <div><dt>No Travel</dt><dd>{formatMiles(route.no_travel_miles)}</dd></div>
      </dl>
      {isAllClear ? (
        <p className="clear-note">✓ 100% clear weather conditions on this route</p>
      ) : (
        recommended && <p className="reason">Chosen for {reason}.</p>
      )}
    </button>
  )
}

export default function RouteCards({ result, selectedId, onSelect }) {
  return (
    <section className="route-cards" aria-label="Routes">
      {!result.travel_advised && (
        <p className="warning" role="alert">
          ⚠ Every route has No Travel conditions. Consider changing the departure time.
        </p>
      )}
      {result.routes.map((route) => (
        <RouteCard
          key={route.id}
          route={route}
          recommended={route.id === result.recommended_route_id}
          reason={result.reason}
          selected={route.id === selectedId}
          onSelect={onSelect}
        />
      ))}
    </section>
  )
}
