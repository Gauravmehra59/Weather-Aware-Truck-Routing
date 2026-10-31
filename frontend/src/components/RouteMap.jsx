import { memo, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { formatDateTime, formatDuration, formatMiles } from '../lib/format'
import { positionAt } from '../lib/heat'
import { RISK_LEVELS, ROUTE_COLORS, riskStyle } from '../lib/risk'
import HeatmapControls from './HeatmapControls'
import HeatmapLayer from './HeatmapLayer'
import RiskLegend from './RiskLegend'

// Continental US center
const DEFAULT_CENTER = [39.5, -98.35]

// Canvas renderer for markers
const renderer = L.canvas({ tolerance: 6 })

const MARKER_STYLES = Object.fromEntries(
  RISK_LEVELS.map((level) => [level.label, { fillColor: level.color, fillOpacity: 1, color: '#1a1a19', weight: 1.5 }]),
)

const truckIcon = L.divIcon({ className: 'truck-icon', html: '🚚', iconSize: [28, 28] })

const originIcon = L.divIcon({
  className: 'endpoint-icon origin-icon',
  html: '<div class="pin pin-origin" title="Origin"><span>A</span></div>',
  iconSize: [28, 28],
  iconAnchor: [14, 26],
})

const destIcon = L.divIcon({
  className: 'endpoint-icon dest-icon',
  html: '<div class="pin pin-dest" title="Destination"><span>B</span></div>',
  iconSize: [28, 28],
  iconAnchor: [14, 26],
})

function TruckMarker({ route, departure, heatmap, hour }) {
  const at = new Date(heatmap.start).getTime() + hour * 3600 * 1000
  const position = positionAt(route, (at - new Date(departure).getTime()) / 1000)
  if (!position) return null
  return (
    <Marker position={position} icon={truckIcon} zIndexOffset={1000}>
      <Tooltip>Route {route.id}: truck position at +{hour} h</Tooltip>
    </Marker>
  )
}

const FOCUS_PADDING = { paddingTopLeft: [40, 40], paddingBottomRight: [40, 64] }

function MapInvalidateHandler({ mobileTab, routes }) {
  const map = useMap()
  useEffect(() => {
    const invalidate = () => {
      map.invalidateSize({ pan: false })
    }

    // Call invalidate across animation frame and several timeout intervals
    invalidate()
    const raf1 = requestAnimationFrame(invalidate)
    const t1 = setTimeout(invalidate, 50)
    const t2 = setTimeout(invalidate, 150)
    const t3 = setTimeout(invalidate, 300)
    const t4 = setTimeout(invalidate, 600)

    const container = map.getContainer()
    let observer
    if (container && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        invalidate()
      })
      observer.observe(container)
    }

    const handleResize = () => invalidate()
    window.addEventListener('resize', handleResize)
    window.addEventListener('orientationchange', handleResize)

    return () => {
      cancelAnimationFrame(raf1)
      clearTimeout(t1)
      clearTimeout(t2)
      clearTimeout(t3)
      clearTimeout(t4)
      if (observer) observer.disconnect()
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('orientationchange', handleResize)
    }
  }, [map, mobileTab, routes])

  return null
}

function FocusSelectedRoute({ route, request, mobileTab }) {
  const map = useMap()
  const handled = useRef(0)
  useEffect(() => {
    if (!route || request === handled.current || mobileTab === 'plan') return
    handled.current = request
    const bounds = L.latLngBounds(route.geometry)
    map.invalidateSize({ pan: false })
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) map.fitBounds(bounds, FOCUS_PADDING)
    else map.flyToBounds(bounds, { ...FOCUS_PADDING, duration: 0.8 })
  }, [map, route, request, mobileTab])
  return null
}

function FitToRoutes({ routes, mobileTab }) {
  const map = useMap()
  useEffect(() => {
    if (!routes?.length) return
    if (mobileTab === 'plan') return

    const bounds = L.latLngBounds(routes.flatMap((route) => route.geometry))
    const fit = () => {
      map.invalidateSize({ pan: false })
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 13 })
    }

    fit()
    const t1 = setTimeout(fit, 80)
    const t2 = setTimeout(fit, 250)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [map, routes, mobileTab])
  return null
}

// Memoised so moving the forecast slider doesn't re-render every marker.
const CheckpointMarker = memo(function CheckpointMarker({ cp, routeId, isSelected = true, showAll = false }) {
  const { weather, risk } = cp
  const routeColor = ROUTE_COLORS[routeId] || '#2a78d6'
  const style = MARKER_STYLES[risk.level]

  const pathOptions = useMemo(() => {
    if (showAll) {
      return {
        fillColor: style.fillColor,
        fillOpacity: 0.9,
        color: routeColor,
        weight: isSelected ? 3.5 : 2.5,
      }
    }
    return {
      ...style,
      color: '#1a1a19',
      weight: 1.5,
    }
  }, [showAll, isSelected, style, routeColor])

  const radius = riskStyle(risk.level).radius + (showAll && isSelected ? 1 : 0)

  return (
    <CircleMarker
      center={[cp.lat, cp.lon]}
      radius={radius}
      pathOptions={pathOptions}
    >
      <Tooltip>
        <div className="cp-tooltip">
          <div style={{ color: routeColor, fontWeight: 700, marginBottom: 2 }}>
            Route {routeId} Checkpoint · Mile {Math.round(cp.mile)}
          </div>
          <strong>{risk.level}</strong>
          {risk.drivers.length > 0 && <span> · {risk.drivers.join(', ')}</span>}
          <div>ETA {formatDateTime(cp.eta)}</div>
          <div>
            Wind <strong>{weather.wind_mph}</strong> mph (gusts {weather.gust_mph})
          </div>
          <div>
            Rain <strong>{weather.rain_in_hr.toFixed(2)}</strong> in/hr · Snow{' '}
            <strong>{weather.snow_in_hr.toFixed(2)}</strong> in/hr
          </div>
        </div>
      </Tooltip>
    </CircleMarker>
  )
})

const RouteLine = memo(function RouteLine({ route, selected, showAll, onSelect, isRecommended }) {
  const handlers = useMemo(() => ({ click: () => onSelect(route.id) }), [onSelect, route.id])
  const routeColor = ROUTE_COLORS[route.id] || '#2a78d6'

  const pathOptions = useMemo(() => {
    if (selected) {
      return { color: routeColor, weight: 6, opacity: 1 }
    }
    if (showAll) {
      // In All Routes mode, each alternative route is drawn brightly in its distinct color!
      return { color: routeColor, weight: 5, opacity: 0.85 }
    }
    return { color: '#898781', weight: 3.5, opacity: 0.5, dashArray: '8 6' }
  }, [selected, showAll, routeColor])

  return (
    <Polyline
      positions={route.geometry}
      pathOptions={pathOptions}
      eventHandlers={handlers}
    >
      <Tooltip sticky>
        <div className="route-tooltip">
          <div className="route-tooltip-title">
            <strong style={{ color: routeColor }}>Route {route.id}</strong>
            {isRecommended && <span className="badge">Recommended</span>}
            {route.is_detour && <span className="tag">via detour</span>}
          </div>
          <div className="route-tooltip-metrics">
            <span>{formatMiles(route.distance_miles)}</span> · <span>{formatDuration(route.duration_s)}</span>
          </div>
          <div>Avg Risk: <strong>{route.avg_risk.toFixed(2)}</strong></div>
          <div className="route-tooltip-risk">
            <span>NT: {formatMiles(route.no_travel_miles)}</span> · 
            <span>Sev: {formatMiles(route.severe_miles)}</span> · 
            <span>High: {formatMiles(route.high_miles)}</span>
          </div>
          <div className="route-tooltip-hint">
            {selected ? '✓ Currently selected route' : '👉 Click route line to select'}
          </div>
        </div>
      </Tooltip>
    </Polyline>
  )
})

export default function RouteMap({ result, selectedId, onSelect, focusRequest, heat, mobileTab }) {
  const [showAllCheckpoints, setShowAllCheckpoints] = useState(false)
  const routes = result?.routes
  // Draw the selected route last so it sits on top of the others.
  const ordered = useMemo(
    () => (routes ? [...routes].sort((a, b) => (a.id === selectedId) - (b.id === selectedId)) : []),
    [routes, selectedId],
  )
  const selected = routes?.find((route) => route.id === selectedId)

  return (
    <div className="map-container">
      <MapContainer center={DEFAULT_CENTER} zoom={4} className="map" renderer={renderer} trackResize={true}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapInvalidateHandler mobileTab={mobileTab} routes={routes} />
        <FitToRoutes routes={routes} mobileTab={mobileTab} />
        <FocusSelectedRoute route={selected} request={focusRequest} mobileTab={mobileTab} />
        {heat.data && <HeatmapLayer heatmap={heat.data} layer={heat.layer} hour={heat.hour} />}
        {ordered.map((route) => (
          <RouteLine
            key={`${route.id}-${route.id === selectedId}-${showAllCheckpoints}`}
            route={route}
            selected={route.id === selectedId}
            showAll={showAllCheckpoints}
            isRecommended={route.id === result?.recommended_route_id}
            onSelect={onSelect}
          />
        ))}

        {/* Origin and Destination Markers */}
        {result?.origin && (
          <Marker position={[result.origin.lat, result.origin.lon]} icon={originIcon} zIndexOffset={900}>
            <Tooltip direction="top" offset={[0, -22]}>
              <div className="endpoint-tooltip">
                <strong>Origin (Start)</strong>
                <div>{result.origin.label}</div>
              </div>
            </Tooltip>
          </Marker>
        )}
        {result?.destination && (
          <Marker position={[result.destination.lat, result.destination.lon]} icon={destIcon} zIndexOffset={900}>
            <Tooltip direction="top" offset={[0, -22]}>
              <div className="endpoint-tooltip">
                <strong>Destination (End)</strong>
                <div>{result.destination.label}</div>
              </div>
            </Tooltip>
          </Marker>
        )}

        {/* Checkpoint Markers (Selected Route or All Routes) */}
        {result && (
          showAllCheckpoints
            ? routes?.flatMap((route) =>
                route.checkpoints.map((cp) => (
                  <CheckpointMarker
                    key={`all-${route.id}-${cp.index}`}
                    cp={cp}
                    routeId={route.id}
                    isSelected={route.id === selectedId}
                    showAll={true}
                  />
                )),
              )
            : selected?.checkpoints.map((cp) => (
                <CheckpointMarker
                  key={`single-${selected.id}-${cp.index}`}
                  cp={cp}
                  routeId={selected.id}
                  isSelected={true}
                  showAll={false}
                />
              ))
        )}

        {selected && heat.data && (
          <TruckMarker route={selected} departure={result.departure} heatmap={heat.data} hour={heat.hour} />
        )}
      </MapContainer>

      {/* On-Map Floating Route Summary Card */}
      {selected && (
        <div className="map-route-summary" aria-label="Selected route summary">
          <div className="map-summary-head">
            <span
              className="route-color-pill"
              style={{ backgroundColor: ROUTE_COLORS[selected.id] || '#2a78d6' }}
            />
            <strong>Route {selected.id}</strong>
            {selected.id === result.recommended_route_id && <span className="badge">Recommended</span>}
            {selected.is_detour && <span className="tag">detour</span>}
            {showAllCheckpoints && <span className="tag" style={{ color: '#2a78d6', fontWeight: 600 }}>All Routes</span>}
          </div>
          <div className="map-summary-stats">
            <span>{formatMiles(selected.distance_miles)}</span>
            <span>{formatDuration(selected.duration_s)}</span>
            <span>Avg Risk: <strong>{selected.avg_risk.toFixed(2)}</strong></span>
          </div>
          <div className="map-summary-risk">
            {selected.no_travel_miles > 0 ? (
              <span className="summary-nt">⚠ No Travel: {formatMiles(selected.no_travel_miles)}</span>
            ) : (
              <span className="summary-safe">✓ Advised</span>
            )}
            <span>Sev: {formatMiles(selected.severe_miles)}</span>
            <span>High: {formatMiles(selected.high_miles)}</span>
          </div>
        </div>
      )}

      {/* Map Bottom Bar: Checkpoints view toggle & Risk legend */}
      {result && (
        <div className="map-bottom-bar">
          {routes?.length > 1 ? (
            <div className="checkpoint-toggle" role="group" aria-label="Checkpoint visibility">
              <span className="toggle-label">View:</span>
              <button
                type="button"
                className={!showAllCheckpoints ? 'active' : ''}
                onClick={() => setShowAllCheckpoints(false)}
              >
                Route {selectedId} Only
              </button>
              <button
                type="button"
                className={showAllCheckpoints ? 'active' : ''}
                onClick={() => setShowAllCheckpoints(true)}
              >
                All {routes.length} Routes
              </button>
            </div>
          ) : (
            <div className="single-route-indicator">
              <span>Showing Route {selectedId} (Single highway corridor)</span>
            </div>
          )}
          <RiskLegend />
        </div>
      )}

      {result && (
        <HeatmapControls
          heatmap={heat.data}
          status={heat.status}
          layer={heat.layer}
          onLayer={heat.setLayer}
          hour={heat.hour}
          onHour={heat.setHour}
          playing={heat.playing}
          onPlaying={heat.setPlaying}
        />
      )}
    </div>
  )
}

