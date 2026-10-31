import { RISK_LEVELS } from './risk'

// Single-hue sequential ramp (light -> dark) for weather magnitudes. Starts at a step
// that still shows up on light map tiles.
const BLUE_RAMP = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b']

// Each weather layer's scale tops out at its No Travel threshold, so a full-dark cell
// means "as bad as it gets". Values under `floor` are drawn transparent.
export const HEAT_LAYERS = {
  risk: { label: 'Risk', key: 'risk' },
  wind: { label: 'Wind', key: 'wind_mph', unit: 'mph', floor: 10, max: 55 },
  rain: { label: 'Rain', key: 'rain_in_hr', unit: 'in/hr', floor: 0.01, max: 1 },
  snow: { label: 'Snow', key: 'snow_in_hr', unit: 'in/hr', floor: 0.01, max: 3 },
}

export const RAMP = BLUE_RAMP

const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
const RAMP_RGB = BLUE_RAMP.map(hexToRgb)
// Low risk stays transparent so only weather worth noticing is painted.
const RISK_RGB = RISK_LEVELS.map((level, i) => (i === 0 ? null : hexToRgb(level.color)))

function colorFor(layer, value) {
  if (layer.key === 'risk') return RISK_RGB[value]
  if (value < layer.floor) return null
  const t = Math.min(1, value / layer.max)
  return RAMP_RGB[Math.min(RAMP_RGB.length - 1, Math.floor(t * RAMP_RGB.length))]
}

/**
 * One image per forecast hour: each grid cell is one pixel. The map stretches the
 * image over the grid bounds and the browser's smoothing blends neighbouring cells.
 * Rendering all frames up front makes scrubbing the slider just an image swap.
 */
export function renderFrames(heatmap, layerName) {
  const layer = HEAT_LAYERS[layerName]
  const series = heatmap[layer.key]
  const canvas = document.createElement('canvas')
  canvas.width = heatmap.cols
  canvas.height = heatmap.rows
  const ctx = canvas.getContext('2d')

  const frames = []
  for (let hour = 0; hour <= heatmap.hours; hour++) {
    const image = ctx.createImageData(heatmap.cols, heatmap.rows)
    heatmap.cells.forEach(([row, col], i) => {
      const rgb = colorFor(layer, series[i][hour])
      if (!rgb) return
      const offset = (row * heatmap.cols + col) * 4
      image.data.set([...rgb, 255], offset)
    })
    ctx.putImageData(image, 0, 0)
    frames.push(canvas.toDataURL())
  }
  return frames
}

/** Where the truck is `seconds` after departure, interpolated between checkpoints. */
export function positionAt(route, seconds) {
  const cps = route.checkpoints
  if (seconds < 0 || seconds > cps[cps.length - 1].elapsed_s) return null
  const next = cps.findIndex((cp) => cp.elapsed_s >= seconds)
  if (next <= 0) return [cps[0].lat, cps[0].lon]
  const a = cps[next - 1]
  const b = cps[next]
  const t = (seconds - a.elapsed_s) / (b.elapsed_s - a.elapsed_s || 1)
  return [a.lat + t * (b.lat - a.lat), a.lon + t * (b.lon - a.lon)]
}
