import { useEffect, useState } from 'react'

const API = '/api'

export default function ClientsMappingPage() {
  const [loading, setLoading] = useState(true)
  const [clients, setClients] = useState([])
  const [scrapeError, setScrapeError] = useState(null)
  const [edits, setEdits] = useState({}) // {siete_id: "team_id string"}
  const [rowState, setRowState] = useState({}) // {siete_id: 'saving' | 'ok' | 'error', msg?}
  const [error, setError] = useState(null)

  function load() {
    setLoading(true)
    setError(null)
    fetch(`${API}/clients/mapping`)
      .then(r => r.json())
      .then(data => {
        const list = data.clients || []
        list.sort((a, b) => (a.siete_name || '').localeCompare(b.siete_name || ''))
        setClients(list)
        setScrapeError(data.scrape_error)
        // Prefill edits with current team_id (so input shows valor actual)
        const initial = {}
        for (const c of list) {
          initial[c.siete_id] = c.team_id == null ? '' : String(c.team_id)
        }
        setEdits(initial)
        setLoading(false)
      })
      .catch(e => {
        setError(`No se pudo cargar el mapeo: ${e.message}`)
        setLoading(false)
      })
  }

  useEffect(() => { load() }, [])

  function handleEdit(siete_id, value) {
    setEdits(prev => ({ ...prev, [siete_id]: value }))
    // Limpiar status anterior si el operador empieza a editar de nuevo
    setRowState(prev => ({ ...prev, [siete_id]: undefined }))
  }

  function parseTeamId(raw) {
    if (raw === '' || raw == null) return null
    const n = parseInt(raw, 10)
    if (isNaN(n) || n <= 0) return undefined // signal inválido
    return n
  }

  function commit(c) {
    const raw = edits[c.siete_id]
    const team_id = parseTeamId(raw)
    if (team_id === undefined) {
      setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'error', msg: 'team_id inválido' } }))
      return
    }
    // No cambio: no llamar
    const current = c.team_id ?? null
    if (team_id === current) return
    setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'saving' } }))
    fetch(`${API}/clients/${c.siete_id}/team-id`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id }),
    })
      .then(async r => {
        const data = await r.json().catch(() => ({}))
        if (!r.ok) {
          throw new Error(data.error || `HTTP ${r.status}`)
        }
        return data
      })
      .then(updated => {
        setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'ok' } }))
        // Refresh la fila localmente
        setClients(prev => prev.map(x =>
          x.siete_id === c.siete_id ? { ...x, team_id: updated.team_id ?? team_id } : x
        ))
      })
      .catch(e => {
        setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'error', msg: e.message } }))
      })
  }

  function clearTeamId(c) {
    if (!confirm(`Desvincular el team_id de "${c.siete_name}"? Quedará en null en Siete.`)) return
    setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'saving' } }))
    fetch(`${API}/clients/${c.siete_id}/team-id`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: null }),
    })
      .then(async r => {
        const data = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`)
        return data
      })
      .then(() => {
        setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'ok' } }))
        setEdits(prev => ({ ...prev, [c.siete_id]: '' }))
        setClients(prev => prev.map(x =>
          x.siete_id === c.siete_id ? { ...x, team_id: null, reply_match: null } : x
        ))
      })
      .catch(e => {
        setRowState(prev => ({ ...prev, [c.siete_id]: { status: 'error', msg: e.message } }))
      })
  }

  if (loading) {
    return <div style={styles.container}><p>Cargando mapeo de clientes…</p></div>
  }

  return (
    <div style={styles.container}>
      <div style={styles.headerRow}>
        <h1 style={styles.title}>Mapeo de Clientes</h1>
        <a href="/reconciliation" style={styles.linkAction}>← Volver a reconciliación</a>
      </div>
      <p style={styles.subtitle}>
        Todos los clientes en Siete con su <code>team_id</code> actual.
        Editá un valor y presioná Enter o salí del campo para guardar (PATCH a Siete).
      </p>

      {scrapeError && (
        <div style={styles.warningCard}>
          ⚠️ Scrape de Reply.io falló: {scrapeError}. La columna "Match Reply.io" no está disponible.
        </div>
      )}

      {error && <div style={styles.errorCard}>{error}</div>}

      <table style={styles.table}>
        <thead>
          <tr style={styles.tr}>
            <th style={styles.th}>Cliente</th>
            <th style={styles.th}>Status</th>
            <th style={styles.th}>team_id</th>
            <th style={styles.th}>Match Reply.io</th>
            <th style={styles.th}></th>
          </tr>
        </thead>
        <tbody>
          {clients.map(c => {
            const rs = rowState[c.siete_id]
            return (
              <tr key={c.siete_id} style={styles.tr}>
                <td style={styles.td}>
                  <strong>{c.siete_name}</strong>
                  <div style={styles.slug}>siete_id: {c.siete_id} · slug: {c.siete_slug}</div>
                </td>
                <td style={styles.td}>{c.status || '—'}</td>
                <td style={styles.td}>
                  <div style={styles.editRow}>
                    <input
                      type="number"
                      min={1}
                      value={edits[c.siete_id] ?? ''}
                      onChange={e => handleEdit(c.siete_id, e.target.value)}
                      onBlur={() => commit(c)}
                      onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
                      style={styles.input}
                      placeholder="—"
                    />
                    {c.team_id != null && (
                      <button
                        type="button"
                        onClick={() => clearTeamId(c)}
                        style={styles.clearButton}
                        title="Desvincular team_id (set null en Siete)"
                      >
                        ×
                      </button>
                    )}
                  </div>
                  {rs?.status === 'saving' && <span style={styles.muted}>Guardando…</span>}
                  {rs?.status === 'ok' && <span style={styles.ok}>✓ OK</span>}
                  {rs?.status === 'error' && <span style={styles.errorInline}>✗ {rs.msg}</span>}
                </td>
                <td style={styles.td}>
                  {c.reply_match ? (
                    <span>{c.reply_match.name} <span style={styles.muted}>({c.reply_match.team_id})</span></span>
                  ) : (
                    <span style={styles.muted}>—</span>
                  )}
                </td>
                <td style={styles.td}></td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div style={styles.actions}>
        <button onClick={load} style={styles.linkButton}>Recargar mapeo</button>
      </div>
    </div>
  )
}

const styles = {
  container: { maxWidth: 1100, margin: '40px auto', padding: '0 20px',
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
  headerRow: { display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 8 },
  title: { fontSize: 24, fontWeight: 600, color: '#1a1a1a' },
  subtitle: { color: '#666', marginBottom: 24, fontSize: 14 },
  linkAction: { fontSize: 12, color: '#2563eb', textDecoration: 'none',
                  padding: '6px 10px', background: '#eff6ff',
                  border: '1px solid #bfdbfe', borderRadius: 6 },
  table: { width: '100%', borderCollapse: 'collapse', marginBottom: 24,
            border: '1px solid #e0e0e0', borderRadius: 6, overflow: 'hidden' },
  tr: { borderBottom: '1px solid #e0e0e0' },
  th: { textAlign: 'left', padding: '12px 14px', background: '#f7f7f7',
         fontSize: 13, fontWeight: 600, color: '#555' },
  td: { padding: '12px 14px', fontSize: 14, verticalAlign: 'top' },
  slug: { fontSize: 11, color: '#999', marginTop: 4 },
  editRow: { display: 'flex', alignItems: 'center', gap: 6 },
  input: { width: 110, padding: '6px 8px', fontSize: 14,
             border: '1px solid #ccc', borderRadius: 4 },
  clearButton: { padding: '4px 8px', background: 'white', color: '#c62828',
                   border: '1px solid #ef9a9a', borderRadius: 4,
                   cursor: 'pointer', fontSize: 14, lineHeight: 1 },
  muted: { color: '#999', fontSize: 12, marginLeft: 6 },
  ok: { color: '#2e7d32', fontSize: 12, marginLeft: 6 },
  errorInline: { color: '#c62828', fontSize: 12, marginLeft: 6 },
  warningCard: { padding: 12, background: '#fff7e0', border: '1px solid #ffd966',
                   borderRadius: 6, marginBottom: 16, fontSize: 14 },
  errorCard: { padding: 12, background: '#ffebee', border: '1px solid #ef9a9a',
                 borderRadius: 6, marginBottom: 16, fontSize: 14, color: '#c62828' },
  actions: { display: 'flex', gap: 12, alignItems: 'center' },
  linkButton: { background: 'none', border: 'none', color: '#666',
                  cursor: 'pointer', fontSize: 13, textDecoration: 'underline' },
}
