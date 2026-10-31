import { useEffect, useId, useRef, useState } from 'react'
import { searchPlaces } from '../api/client'

const DEBOUNCE_MS = 150
const MIN_CHARS = 3

// In-memory cache for instant suggestions across typing, backspacing and repetitive queries
const queryCache = new Map()

/**
 * Text input with place suggestions (ARIA combobox). `value` is
 * { text, point }: point is [lat, lon] once a suggestion is picked and is cleared
 * as soon as the text is edited again.
 */
export default function PlaceInput({ label, value, onChange, placeholder }) {
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(-1)
  const listId = useId()
  const pending = useRef(null)

  const query = value.text.trim()
  const normalizedQuery = query.toLowerCase()
  const searching = !value.point && query.length >= MIN_CHARS

  useEffect(() => {
    if (!searching) return

    // Return cached results immediately with 0 delay
    if (queryCache.has(normalizedQuery)) {
      const timer = setTimeout(() => {
        setSuggestions(queryCache.get(normalizedQuery))
        setActive(-1)
      }, 0)
      return () => clearTimeout(timer)
    }

    const timer = setTimeout(async () => {
      setLoading(true)
      pending.current?.abort()
      const controller = new AbortController()
      pending.current = controller
      try {
        const results = await searchPlaces(query, controller.signal)
        if (controller.signal.aborted) return
        queryCache.set(normalizedQuery, results)
        setSuggestions(results)
        setActive(-1)
      } catch {
        if (!controller.signal.aborted) setSuggestions([])
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      setLoading(false)
    }
  }, [query, searching, normalizedQuery])

  useEffect(() => () => pending.current?.abort(), [])

  function pick(suggestion) {
    onChange({ text: suggestion.label, point: [suggestion.lat, suggestion.lon] })
    setOpen(false)
  }

  const expanded = open && searching && suggestions.length > 0

  function handleKeyDown(event) {
    if (!expanded) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((i) => (i + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1))
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault()
      pick(suggestions[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <label className="place-input">
      <div className="place-input-header">
        <span>{label}</span>
        {loading && <span className="place-spinner" aria-hidden="true" title="Searching places…" />}
      </div>
      <input
        required
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        value={value.text}
        placeholder={placeholder}
        onChange={(event) => {
          onChange({ text: event.target.value, point: null })
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={handleKeyDown}
      />
      {expanded && (
        <ul className="suggestions" role="listbox" id={listId}>
          {suggestions.map((suggestion, i) => (
            <li
              key={`${suggestion.label}-${suggestion.lat}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseDown={(event) => {
                event.preventDefault()
                pick(suggestion)
              }}
              onMouseEnter={() => setActive(i)}
            >
              {suggestion.label}
            </li>
          ))}
        </ul>
      )}
    </label>
  )
}
