import { useEffect, useState } from 'react'

const API = '/api'

export default function DownloadLogsPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/last-run`)
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

  const okClients = data?.clients?.filter(c => c.status === 'ok') ?? []
  const failedClients = data?.clients?.filter(c => c.status === 'failed') ?? []

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <a href="/" style={styles.back}>← Volver</a>
        <h1 style={styles.title}>Logs de descarga</h1>
        {data?.date && (
          <p style={styles.subtitle}>
            Corrida del {data.date} · {data.ok_count}/{data.total} clientes OK
          </p>
        )}
      </div>

      {loading && <p style={styles.muted}>Cargando...</p>}
      {error && <div style={styles.errorCard}><p style={styles.errorText}>{error}</p></div>}

      {data && (
        <div style={styles.tableCard}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Estado</th>
                <th style={styles.th}>Cliente</th>
                <th style={{ ...styles.th, color: '#888' }}>Detalle / Error</th>
              </tr>
            </thead>
            <tbody>
              {data.clients.map((c, i) => (
                <tr key={c.name} style={i % 2 === 0 ? styles.rowEven : styles.rowOdd}>
                  <td style={{ ...styles.td, width: 36, textAlign: 'center' }}>
                    {c.status === 'ok'
                      ? <span style={styles.ok}>✓</span>
                      : <span style={styles.fail}>✗</span>}
                  </td>
                  <td style={{ ...styles.td, fontWeight: c.status === 'ok' ? 500 : 400 }}>
                    {c.name}
                  </td>
                  <td style={{ ...styles.td, color: c.status === 'ok' ? '#888' : '#b91c1c', fontSize: 12 }}>
                    {c.status === 'ok' ? 'Descargado' : c.error}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3} style={{ ...styles.td, fontWeight: 600, fontSize: 13, color: '#555' }}>
                  {okClients.length} exitosos · {failedClients.length} fallidos · {data.total} total
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
    maxWidth: 800,
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
  ok:   { color: '#16a34a', fontWeight: 700, fontSize: 16 },
  fail: { color: '#dc2626', fontWeight: 700, fontSize: 16 },
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
