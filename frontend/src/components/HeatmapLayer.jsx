import { useEffect, useMemo } from 'react'
import { ImageOverlay, Pane } from 'react-leaflet'
import { renderFrames } from '../lib/heat'

// Above the map tiles (200) but below route lines and markers (400).
const PANE_STYLE = { zIndex: 350 }

export default function HeatmapLayer({ heatmap, layer, hour }) {
  const frames = useMemo(() => renderFrames(heatmap, layer), [heatmap, layer])

  // Decode every frame up front so scrubbing never waits on a first-time decode.
  useEffect(() => {
    for (const src of frames) {
      const img = new Image()
      img.src = src
      img.decode().catch(() => {})
    }
  }, [frames])

  return (
    <Pane name="heatmap" style={PANE_STYLE}>
      <ImageOverlay url={frames[hour]} bounds={heatmap.bounds} opacity={0.6} className="heatmap-image" />
    </Pane>
  )
}
