import { formatDateTime } from '../lib/format'
import { riskStyle } from '../lib/risk'

export default function CheckpointTable({ route }) {
  return (
    <details className="checkpoint-table">
      <summary>Route {route.id} checkpoints ({route.checkpoints.length})</summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Mile</th>
              <th>ETA</th>
              <th>Risk</th>
              <th>Wind mph</th>
              <th>Rain in/hr</th>
              <th>Snow in/hr</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((cp) => (
              <tr key={cp.index}>
                <td>{Math.round(cp.mile)}</td>
                <td>{formatDateTime(cp.eta)}</td>
                <td>
                  <span className="dot" style={{ background: riskStyle(cp.risk.level).color }} />
                  {cp.risk.level}
                </td>
                <td>{cp.weather.wind_mph}</td>
                <td>{cp.weather.rain_in_hr.toFixed(2)}</td>
                <td>{cp.weather.snow_in_hr.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
