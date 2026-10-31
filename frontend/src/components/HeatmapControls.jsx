import { useEffect, useState } from 'react'
import { formatDateTime } from '../lib/format'
import { HEAT_LAYERS, RAMP } from '../lib/heat'

const PLAY_STEP_MS = 400

function ScaleBar({ layer }) {
  return (
    <div className="scale-bar">
      <span>{layer.floor}</span>
      <span className="scale-ramp" style={{ background: `linear-gradient(to right, ${RAMP.join(', ')})` }} />
      <span>{layer.max}+ {layer.unit}</span>
    </div>
  )
}

export default function HeatmapControls({ heatmap, status, layer, onLayer, hour, onHour, playing, onPlaying }) {
  const [mobileExpanded, setMobileExpanded] = useState(false)

  useEffect(() => {
    if (!playing || !heatmap) return
    if (hour >= heatmap.hours) {
      onPlaying(false)
      return
    }
    const timer = setTimeout(() => onHour(hour + 1), PLAY_STEP_MS)
    return () => clearTimeout(timer)
  }, [playing, hour, heatmap, onHour, onPlaying])

  if (status === 'loading') return <div className="heat-status-pill">Loading forecast…</div>
  if (status === 'error') return <div className="heat-status-pill error">Forecast unavailable</div>
  if (!heatmap) return null

  const time = new Date(new Date(heatmap.start).getTime() + hour * 3600 * 1000)
  const togglePlay = () => {
    if (!playing && hour >= heatmap.hours) onHour(0)
    onPlaying(!playing)
  }

  const currentLayer = HEAT_LAYERS[layer]

  return (
    <div className="heat-controls-wrapper">
      {/* Mobile Compact Trigger Button (visible only on mobile) */}
      <button
        type="button"
        className={`heat-mobile-trigger ${mobileExpanded ? 'active' : ''}`}
        onClick={() => setMobileExpanded((prev) => !prev)}
        aria-label="Toggle forecast controls"
      >
        <span>🌦️ {currentLayer?.label || 'Forecast'}</span>
        <span className="heat-mobile-hour">+{hour}h</span>
        <span>{mobileExpanded ? '✕' : '▾'}</span>
      </button>

      {/* Main Controls Panel (always visible on desktop, toggleable on mobile) */}
      <div className={`heat-controls ${mobileExpanded ? 'mobile-visible' : ''}`}>
        <div className="heat-panel-header">
          <span className="heat-panel-title">48-Hour Forecast Corridor</span>
          <button
            type="button"
            className="heat-panel-close"
            onClick={() => setMobileExpanded(false)}
            aria-label="Close forecast panel"
          >
            ✕
          </button>
        </div>

        <div className="heat-row">
          <div className="segmented" role="radiogroup" aria-label="Heatmap layer">
            {Object.entries(HEAT_LAYERS).map(([name, def]) => (
              <button
                key={name}
                type="button"
                role="radio"
                aria-checked={layer === name}
                className={layer === name ? 'active' : ''}
                onClick={() => onLayer(name)}
              >
                {def.label}
              </button>
            ))}
          </div>
        </div>
        <div className="heat-row">
          <button type="button" className="play" onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? '❚❚' : '▶'}
          </button>
          <input
            type="range"
            min="0"
            max={heatmap.hours}
            value={hour}
            onChange={(e) => {
              onPlaying(false)
              onHour(Number(e.target.value))
            }}
            aria-label="Forecast hour"
          />
        </div>
        <div className="heat-time">
          <strong>+{hour} h</strong> · {formatDateTime(time.toISOString())}
        </div>
        {layer !== 'risk' && <ScaleBar layer={HEAT_LAYERS[layer]} />}
      </div>
    </div>
  )
}
