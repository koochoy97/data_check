import { useEffect, useState } from 'react'

const API = '/api'

export default function DownloadLogsPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/client-stats`)
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setData(d)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <a href="/" style={styles.back}>← Volver</a>
        <h1 style={styles.title}>Logs de descarga</h1>
        {data?.date && <p style={styles.subtitle}>Datos del {data.date}</p>}
      </div>

      {loading && <p style={styles.muted}>Cargando...</p>}
      {error && <div style={styles.errorCard}><p style={styles.errorText}>{error}</p></div>}

      {data && (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Cliente</th>
                <th style={{ ...styles.th, textAlign: 'right' }}>People</th>
                <th style={{ ...styles.th, textAlign: 'right' }}>Email Activity</th>
              </tr>
            </thead>
            <tbody>
              {data.clients.map((c, i) => (
                <tr key={c.name} style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}>
                  <td style={styles.td}>{c.name}</td>
                  <td style={{ ...styles.td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {c.people.toLocaleString()}
                  </td>
                  <td style={{ ...styles.td, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {c.email_activity.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td style={{ ...styles.td, fontWeight: 600 }}>Total</td>
                <td style={{ ...styles.td, textAlign: 'right', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                  {data.clients.reduce((s, c) => s + c.people, 0).toLocaleString()}
                </td>
                <td style={{ ...styles.td, textAlign: 'right', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                  {data.clients.reduce((s, c) => s + c.email_activity, 0).toLocaleString()}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    maxWidth: 700,
    margin: '40px auto',
    padding: '0 20px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  header: {
    marginBottom: 24,
  },
  back: {
    fontSize: 13,
    color: '#2563eb',
    textDecoration: 'none',
    display: 'inline-block',
    marginBottom: 12,
  },
  title: {
    fontSize: 22,
    fontWeight: 600,
    color: '#1a1a1a',
    margin: '0 0 4px',
  },
  subtitle: {
    fontSize: 13,
    color: '#888',
    margin: 0,
  },
  muted: {
    color: '#888',
    fontSize: 14,
  },
  tableCard: {
    background: '#fff',
    border: '1px solid #e0e0e0',
    borderRadius: 8,
    overflow: 'hidden',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 14,
  },
  th: {
    padding: '10px 16px',
    background: '#f8f9fa',
    color: '#555',
    fontWeight: 600,
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    borderBottom: '1px solid #e0e0e0',
    textAlign: 'left',
  },
  td: {
    padding: '9px 16px',
    color: '#1a1a1a',
    borderBottom: '1px solid #f0f0f0',
  },
  rowEven: { background: '#fff' },
  rowOdd:  { background: '#fafafa' },
  errorCard: {
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 8,
    padding: 16,
  },
  errorText: {
    color: '#991b1b',
    margin: 0,
    fontSize: 14,
  },
}
