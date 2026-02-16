import { useState, useEffect, useRef } from 'react'

const API = '/api'

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

export default function App() {
  const [clients, setClients] = useState([])
  const [selected, setSelected] = useState('')
  const [logs, setLogs] = useState([])
  const [running, setRunning] = useState(false)
  const [sheetUrl, setSheetUrl] = useState(null)
  const [files, setFiles] = useState([])
  const [error, setError] = useState(null)
  const logEndRef = useRef(null)

  useEffect(() => {
    fetch(`${API}/clients`)
      .then(r => r.json())
      .then(data => {
        setClients(data)
        if (data.length > 0) setSelected(data[0].id)
      })
      .catch(() => setError('No se pudo conectar al backend'))
  }, [])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  function handleGenerate() {
    if (!selected || running) return
    setRunning(true)
    setLogs([])
    setSheetUrl(null)
    setFiles([])
    setError(null)

    const es = new EventSource(`${API}/generate/${selected}`)

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'progress') {
          setLogs(prev => [...prev, data.message])
        } else if (data.type === 'file') {
          setFiles(prev => [...prev, { name: data.name, size: data.size, path: data.path }])
        } else if (data.type === 'done') {
          setLogs(prev => [...prev, data.message])
          setSheetUrl(data.url)
          setRunning(false)
          es.close()
        } else if (data.type === 'error') {
          setError(data.message)
          setRunning(false)
          es.close()
        }
      } catch (e) {
        console.error('SSE parse error:', e, event.data)
      }
    }

    es.onerror = (e) => {
      console.error('SSE error:', e)
      if (running) {
        setError('Conexion perdida con el servidor')
        setRunning(false)
      }
      es.close()
    }
  }

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Reply.io Report Validator</h1>

      <div style={styles.card}>
        <label style={styles.label}>Cliente</label>
        <select
          value={selected}
          onChange={e => setSelected(e.target.value)}
          disabled={running}
          style={styles.select}
        >
          {clients.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <button
          onClick={handleGenerate}
          disabled={running || !selected}
          style={{
            ...styles.button,
            opacity: running ? 0.6 : 1,
            cursor: running ? 'wait' : 'pointer',
          }}
        >
          {running ? 'Generando...' : 'Generar Reporte'}
        </button>
      </div>

      {logs.length > 0 && (
        <div style={styles.logCard}>
          <h3 style={styles.logTitle}>Progreso</h3>
          <div style={styles.logContainer}>
            {logs.map((log, i) => (
              <div key={i} style={styles.logLine}>
                <span style={styles.logDot}>
                  {i === logs.length - 1 && running ? '>' : ' '}
                </span>
                {log}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {sheetUrl && (
        <div style={styles.successCard}>
          <p style={styles.successText}>Reporte generado exitosamente</p>
          <a
            href={sheetUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.link}
          >
            Abrir Google Sheet
          </a>
        </div>
      )}

      {files.length > 0 && (
        <div style={styles.filesCard}>
          <h3 style={styles.filesTitle}>Archivos descargados</h3>
          {files.map((f, i) => (
            <a
              key={i}
              href={f.path}
              download={f.name}
              style={styles.fileRow}
            >
              <span>{f.name}</span>
              <span style={styles.fileSize}>{formatBytes(f.size)}</span>
            </a>
          ))}
        </div>
      )}

      {error && (
        <div style={styles.errorCard}>
          <p style={styles.errorText}>{error}</p>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    maxWidth: 600,
    margin: '40px auto',
    padding: '0 20px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  title: {
    fontSize: 24,
    fontWeight: 600,
    marginBottom: 24,
    color: '#1a1a1a',
  },
  card: {
    background: '#fff',
    border: '1px solid #e0e0e0',
    borderRadius: 8,
    padding: 24,
    marginBottom: 16,
  },
  label: {
    display: 'block',
    fontSize: 14,
    fontWeight: 500,
    marginBottom: 8,
    color: '#555',
  },
  select: {
    width: '100%',
    padding: '10px 12px',
    fontSize: 15,
    border: '1px solid #d0d0d0',
    borderRadius: 6,
    marginBottom: 16,
    outline: 'none',
  },
  button: {
    width: '100%',
    padding: '12px',
    fontSize: 15,
    fontWeight: 600,
    color: '#fff',
    background: '#2563eb',
    border: 'none',
    borderRadius: 6,
  },
  logCard: {
    background: '#1a1a2e',
    border: '1px solid #333',
    borderRadius: 8,
    padding: 20,
    marginBottom: 16,
  },
  logTitle: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 12,
    color: '#888',
  },
  logContainer: {
    fontFamily: 'monospace',
    fontSize: 13,
    lineHeight: 1.8,
    maxHeight: 300,
    overflowY: 'auto',
  },
  logLine: {
    color: '#e0e0e0',
  },
  logDot: {
    color: '#4ade80',
    marginRight: 8,
  },
  successCard: {
    background: '#f0fdf4',
    border: '1px solid #bbf7d0',
    borderRadius: 8,
    padding: 20,
    textAlign: 'center',
    marginBottom: 16,
  },
  successText: {
    color: '#166534',
    fontWeight: 600,
    marginBottom: 12,
  },
  link: {
    display: 'inline-block',
    padding: '10px 24px',
    background: '#16a34a',
    color: '#fff',
    borderRadius: 6,
    textDecoration: 'none',
    fontWeight: 600,
  },
  filesCard: {
    background: '#fff',
    border: '1px solid #e0e0e0',
    borderRadius: 8,
    padding: 20,
    marginBottom: 16,
  },
  filesTitle: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 12,
    color: '#555',
  },
  fileRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 12px',
    background: '#f8f9fa',
    borderRadius: 6,
    marginBottom: 8,
    textDecoration: 'none',
    color: '#2563eb',
    fontWeight: 500,
    fontSize: 14,
  },
  fileSize: {
    color: '#888',
    fontSize: 13,
    fontWeight: 400,
  },
  errorCard: {
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 8,
    padding: 16,
  },
  errorText: {
    color: '#991b1b',
    margin: 0,
  },
}
