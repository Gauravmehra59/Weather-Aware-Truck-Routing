import { useState } from 'react'
import { nextHourLocalInput } from '../lib/format'
import PlaceInput from './PlaceInput'

const INTERVALS = [10, 25, 50]

export default function TripForm({ onSubmit, loading }) {
  const [form, setForm] = useState({
    origin: { text: '', point: null },
    destination: { text: '', point: null },
    departure: nextHourLocalInput(),
    load_lb: 35000,
    interval_miles: 25,
  })

  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value })
  const updatePlace = (field) => (place) => setForm({ ...form, [field]: place })

  function handleSubmit(event) {
    event.preventDefault()
    const { origin, destination, ...rest } = form
    onSubmit({
      ...rest,
      origin: origin.text,
      destination: destination.text,
      // Exact coordinates of a picked suggestion, so the backend routes to that place.
      ...(origin.point && { origin_point: origin.point }),
      ...(destination.point && { destination_point: destination.point }),
      // datetime-local is the user's local time; send an unambiguous UTC instant.
      departure: new Date(form.departure).toISOString(),
      load_lb: Number(form.load_lb),
      interval_miles: Number(form.interval_miles),
    })
  }

  return (
    <form className="trip-form" onSubmit={handleSubmit}>
      <PlaceInput label="Origin" value={form.origin} onChange={updatePlace('origin')} placeholder="Chicago, IL" />
      <PlaceInput label="Destination" value={form.destination} onChange={updatePlace('destination')} placeholder="Denver, CO" />
      <label>
        Departure
        <input required type="datetime-local" value={form.departure} onChange={update('departure')} />
      </label>
      <div className="form-row">
        <label>
          Load (lb)
          <input required type="number" min="0" max="200000" step="500" value={form.load_lb} onChange={update('load_lb')} />
        </label>
        <label>
          Weather every
          <select value={form.interval_miles} onChange={update('interval_miles')}>
            {INTERVALS.map((miles) => (
              <option key={miles} value={miles}>{miles} miles</option>
            ))}
          </select>
        </label>
      </div>
      <button type="submit" className={loading ? 'loading' : ''} disabled={loading}>
        {loading ? (
          <span className="btn-loading-content">
            <span className="spinner-inline" aria-hidden="true" />
            Analyzing routes & weather…
          </span>
        ) : (
          'Find safest route'
        )}
      </button>
      {loading && (
        <div className="planning-status-bar" role="status">
          <span className="pulse-dot" />
          <span>Evaluating corridors & live weather checkpoints…</span>
        </div>
      )}
    </form>
  )
}
