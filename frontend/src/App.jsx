import { useCallback, useRef, useState } from 'react'
import { getHeatmap, planTrip } from './api/client'
import CheckpointTable from './components/CheckpointTable'
import PwaInstallButton from './components/PwaInstallButton'
import RouteCards from './components/RouteCards'
import RouteMap from './components/RouteMap'
import TripForm from './components/TripForm'

export default function App() {
  const [result, setResult] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  // Bumped whenever the user picks a route, telling the map to bring it into view.
  const [focusRequest, setFocusRequest] = useState(0)
  const mapRef = useRef(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mobileTab, setMobileTab] = useState('plan') // 'plan' | 'map'

  const [heatmap, setHeatmap] = useState(null)
  const [heatStatus, setHeatStatus] = useState('idle')
  const [heatLayer, setHeatLayer] = useState('risk')
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  // Each plan gets an id; a late heatmap response for an older plan is dropped.
  const planRequest = useRef(0)

  async function loadHeatmap(plan, requestId) {
    setHeatStatus('loading')
    try {
      const data = await getHeatmap({
        departure: plan.departure,
        load_lb: plan.load_lb,
        paths: plan.routes.map((route) => route.geometry),
      })
      if (requestId !== planRequest.current) return
      setHeatmap(data)
      setHeatStatus('ready')
    } catch {
      if (requestId === planRequest.current) setHeatStatus('error')
    }
  }

  async function handlePlan(payload) {
    const requestId = ++planRequest.current
    setLoading(true)
    setError(null)
    setPlaying(false)
    try {
      const data = await planTrip(payload)
      if (requestId !== planRequest.current) return
      setResult(data)
      setSelectedId(data.recommended_route_id)
      setHeatmap(null)
      setHour(0)
      // Switch mobile view to map automatically once routes are calculated
      if (window.innerWidth <= 768) {
        setMobileTab('map')
      }
      // The plan is shown right away; the heatmap fills in when it arrives.
      loadHeatmap(data, requestId)
    } catch (err) {
      if (requestId === planRequest.current) setError(err.message)
    } finally {
      if (requestId === planRequest.current) setLoading(false)
    }
  }

  const selectRoute = useCallback((id) => {
    setSelectedId(id)
    setFocusRequest((n) => n + 1)
    if (window.innerWidth <= 768) {
      setMobileTab('map')
    }
    // On narrow screens the map sits below the route list; scroll to it unless at
    // least half of it is already on screen (a sliver at the bottom doesn't count).
    const rect = mapRef.current?.getBoundingClientRect()
    const visible = rect ? Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0) : 0
    if (rect && visible < rect.height / 2) {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      mapRef.current.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
    }
  }, [])

  const selected = result?.routes.find((route) => route.id === selectedId)
  const heat = {
    data: heatmap,
    status: heatStatus,
    layer: heatLayer,
    setLayer: setHeatLayer,
    hour,
    setHour,
    playing,
    setPlaying,
  }

  return (
    <div className={`app mobile-view-${mobileTab}`}>
      {/* Mobile Top Navigation Tab Bar */}
      <nav className="mobile-nav-bar" aria-label="Mobile View Switcher">
        <button
          type="button"
          className={`mobile-nav-tab ${mobileTab === 'plan' ? 'active' : ''}`}
          onClick={() => setMobileTab('plan')}
        >
          📋 Trip Plan
        </button>
        <button
          type="button"
          className={`mobile-nav-tab ${mobileTab === 'map' ? 'active' : ''}`}
          onClick={() => setMobileTab('map')}
        >
          🗺️ Map & Heatmap
          {result?.routes && <span className="tab-pill">{result.routes.length}</span>}
        </button>
      </nav>

      <aside className={`sidebar ${mobileTab === 'map' ? 'mobile-hidden' : ''}`}>
        <header className="sidebar-header">
          <h1>Weather-Aware Truck Routing</h1>
          <PwaInstallButton />
        </header>
        <TripForm onSubmit={handlePlan} loading={loading} />
        {error && <p className="error" role="alert">{error}</p>}
        {result && (
          // Keep the previous result visible (dimmed) while a new plan loads.
          <div className={loading ? 'results stale' : 'results'}>
            <p className="trip-summary">
              {result.origin.label.split(',')[0]} → {result.destination.label.split(',')[0]}
            </p>
            <RouteCards result={result} selectedId={selectedId} onSelect={selectRoute} />
            {selected && <CheckpointTable route={selected} />}
          </div>
        )}
        <footer className="app-footer">
          <div className="author-card">
            <div className="author-header">
              <span className="author-label">Developed by</span>
              <strong className="author-name">Gaurav Mehra</strong>
            </div>
            <a
              href="mailto:gauravmehra930@gmail.com"
              className="author-email-link"
              title="Send email to Gaurav Mehra"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="20" height="16" x="2" y="4" rx="2"/>
                <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>
              </svg>
              gauravmehra930@gmail.com
            </a>
          </div>
        </footer>
      </aside>
      <main className={`map-wrapper ${mobileTab === 'plan' ? 'mobile-hidden' : ''}`} ref={mapRef}>
        <RouteMap
          result={result}
          selectedId={selectedId}
          onSelect={selectRoute}
          focusRequest={focusRequest}
          heat={heat}
          mobileTab={mobileTab}
        />
      </main>
    </div>
  )
}
