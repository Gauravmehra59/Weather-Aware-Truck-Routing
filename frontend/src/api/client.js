const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/** Turn a DRF error body into one readable sentence. */
function errorMessage(body, status) {
  if (body?.detail) return body.detail
  if (body && typeof body === 'object') {
    return Object.entries(body)
      .map(([field, messages]) => {
        const text = [].concat(messages).join(' ')
        return field === 'non_field_errors' ? text : `${field.replace('_', ' ')}: ${text}`
      })
      .join(' ')
  }
  return `Request failed (${status})`
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`${BASE_URL}/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new Error('Cannot reach the server. Is the backend running?')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(errorMessage(body, res.status))
  return body
}

export const getHealth = () => request('/health/')

export const planTrip = (payload) =>
  request('/plan/', { method: 'POST', body: JSON.stringify(payload) })

export const searchPlaces = (query, signal) =>
  request(`/places/?q=${encodeURIComponent(query)}`, { signal })

export const getHeatmap = (payload) =>
  request('/heatmap/', { method: 'POST', body: JSON.stringify(payload) })
