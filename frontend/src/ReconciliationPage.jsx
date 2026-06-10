import { useEffect, useState } from 'react'

const API = '/api'

export default function ReconciliationPage() {
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState([])
  const [replyOptions, setReplyOptions] = useState([])
  const [scrapeError, setScrapeError] = useState(null)
  const [selections, setSelections] = useState({}) // {siete_id: team_id_or_'__manual'}
  const [manualInputs, setManualInputs] = useState({}) // {siete_id: "team_id string"}
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [discardedOpen, setDiscardedOpen] = useState(false)
  const [discarded, setDiscarded] = useState([])
  const [discardedLoading, setDiscardedLoading] = useState(false)

  function loadPending() {
    setLoading(true)
    setError(null)
    setResult(null)
    fetch(`${API}/reconciliation/pending`)
      .then(r => r.json())
      .then(data => {
        setPending(data.pending || [])
        setReplyOptions(data.reply_options || [])
        setScrapeError(data.scrape_error)
        // Prefill selections from suggestions
        const initial = {}
        for (const p of data.pending || []) {
          if (p.suggested && p.suggested.confidence === 'exact') {
            initial[p.siete_id] = p.suggested.team_id
          }
        }
        setSelections(initial)
        setLoading(false)
      })
      .catch(e => {
        setError(`No se pudo cargar la lista: ${e.message}`)
        setLoading(false)
      })
  }

  useEffect(() => { loadPending() }, [])

  function loadDiscarded() {
    setDiscardedLoading(true)
    fetch(`${API}/reconciliation/discarded`)
      .then(r => r.json())
      .then(data => {
        setDiscarded(data.discarded || [])
        setDiscardedLoading(false)
      })
      .catch(e => {
        setError(`No se pudo cargar descartados: ${e.message}`)
        setDiscardedLoading(false)
      })
  }

  function handleDiscard(siete_id, siete_name) {
    if (!confirm(`Descartar a "${siete_name}"? No aparecerá más como pendiente (no toca Siete).`)) return
    fetch(`${API}/reconciliation/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ siete_id }),
    })
      .then(r => r.json())
      .then(() => {
        loadPending()
        if (discardedOpen) loadDiscarded()
      })
      .catch(e => setError(`Error descartando: ${e.message}`))
  }

  function handleRestore(siete_id) {
    fetch(`${API}/reconciliation/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ siete_id }),
    })
      .then(r => r.json())
      .then(() => {
        loadDiscarded()
        loadPending()
      })
      .catch(e => setError(`Error restaurando: ${e.message}`))
  }

  function toggleDiscarded() {
    const next = !discardedOpen
    setDiscardedOpen(next)
    if (next && discarded.length === 0) loadDiscarded()
  }

  function handleSelect(siete_id, value) {
    setSelections(prev => ({ ...prev, [siete_id]: value }))
  }

  function handleManual(siete_id, value) {
    setManualInputs(prev => ({ ...prev, [siete_id]: value }))
  }

  function buildPayload() {
    const items = []
    for (const p of pending) {
      const sel = selections[p.siete_id]
      let team_id = null
      if (sel === '__manual') {
        const raw = manualInputs[p.siete_id]
        const parsed = parseInt(raw, 10)
        if (!isNaN(parsed) && parsed > 0) team_id = parsed
      } else if (typeof sel === 'number' && sel > 0) {
        team_id = sel
      }
      if (team_id) {
        items.push({ siete_id: p.siete_id, team_id })
      }
    }
    return items
  }

  function handleSave() {
    const items = buildPayload()
    if (items.length === 0) {
      setError('Selecciona al menos un cliente y elegí un workspace')
      return
    }
    setSaving(true)
    setError(null)
    setResult(null)
    fetch(`${API}/reconciliation/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(items),
    })
      .then(r => r.json())
      .then(data => {
        setResult(data)
        setSaving(false)
        // Reload to show only the still-pending ones
        loadPending()
      })
      .catch(e => {
        setError(`Error guardando: ${e.message}`)
        setSaving(false)
      })
  }

  if (loading) {
    return <div style={styles.container}><p>Cargando clientes pendientes...</p></div>
  }

  return (
    <div style={styles.container}>
      <div style={styles.headerRow}>
        <h1 style={styles.title}>Reconciliación de Clientes</h1>
        <a href="/clients" style={styles.linkAction}>Ver mapeo completo →</a>
      </div>
      <p style={styles.subtitle}>
        Clientes activos en Siete sin <code>team_id</code> de Reply.io.
        Elegí el workspace correspondiente y guardá; se actualiza Siete via PATCH.
      </p>

      {scrapeError && (
        <div style={styles.warningCard}>
          ⚠️ Scrape de Reply.io falló: {scrapeError}. Podés tipear el <code>team_id</code> manualmente.
        </div>
      )}

      {pending.length === 0 ? (
        <div style={styles.successCard}>✅ Sin clientes pendientes de reconciliación</div>
      ) : (
        <>
          <table style={styles.table}>
            <thead>
              <tr style={styles.tr}>
                <th style={styles.th}>#</th>
                <th style={styles.th}>Cliente Siete</th>
                <th style={styles.th}>Workspace Reply.io</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p, idx) => {
                const sel = selections[p.siete_id]
                return (
                  <tr key={p.siete_id} style={styles.tr}>
                    <td style={styles.td}>{idx + 1}</td>
                    <td style={styles.td}>
                      <strong>{p.siete_name}</strong>
                      <div style={styles.slug}>siete_id: {p.siete_id} · slug: {p.siete_slug}</div>
                      {p.suggested && (
                        <div style={styles.suggestion}>
                          💡 Sugerencia ({p.suggested.confidence}): {p.suggested.name} (team_id {p.suggested.team_id})
                        </div>
                      )}
                    </td>
                    <td style={styles.td}>
                      <select
                        style={styles.select}
                        value={sel ?? ''}
                        onChange={e => {
                          const v = e.target.value
                          if (v === '__manual') handleSelect(p.siete_id, '__manual')
                          else if (v === '') handleSelect(p.siete_id, undefined)
                          else handleSelect(p.siete_id, parseInt(v, 10))
                        }}
                      >
                        <option value="">— elegir —</option>
                        {replyOptions.map(w => (
                          <option key={w.team_id} value={w.team_id}>
                            {w.name} (team_id {w.team_id})
                          </option>
                        ))}
                        <option value="__manual">✍️ Tipear team_id manualmente…</option>
                      </select>
                      {sel === '__manual' && (
                        <input
                          type="number"
                          placeholder="team_id"
                          value={manualInputs[p.siete_id] ?? ''}
                          onChange={e => handleManual(p.siete_id, e.target.value)}
                          style={styles.manualInput}
                        />
                      )}
                    </td>
                    <td style={styles.td}>
                      <button
                        type="button"
                        onClick={() => handleDiscard(p.siete_id, p.siete_name)}
                        style={styles.discardButton}
                        title="Descartar localmente (no toca Siete)"
                      >
                        Descartar
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div style={styles.actions}>
            <button
              onClick={handleSave}
              disabled={saving || buildPayload().length === 0}
              style={{
                ...styles.button,
                opacity: saving || buildPayload().length === 0 ? 0.5 : 1,
                cursor: saving ? 'wait' : 'pointer',
              }}
            >
              {saving ? 'Guardando…' : `Guardar ${buildPayload().length} match${buildPayload().length === 1 ? '' : 'es'}`}
            </button>
            <button onClick={loadPending} disabled={saving} style={styles.linkButton}>
              Recargar lista
            </button>
          </div>
        </>
      )}

      {result && (
        <div style={styles.resultCard}>
          <h3>Resultado</h3>
          <p>✓ Guardados: {result.saved.length}</p>
          {result.saved.map((s, i) => (
            <div key={i} style={styles.savedRow}>
              {s.client_name} → team_id {s.team_id}
            </div>
          ))}
          {result.errors.length > 0 && (
            <>
              <p style={styles.errorText}>✗ Errores: {result.errors.length}</p>
              {result.errors.map((e, i) => (
                <div key={i} style={styles.errorRow}>
                  siete_id {e.siete_id}: {e.reason}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {error && <div style={styles.errorCard}>{error}</div>}

      <div style={styles.discardedSection}>
        <button type="button" onClick={toggleDiscarded} style={styles.discardedToggle}>
          {discardedOpen ? '▼' : '▶'} Clientes descartados {discarded.length > 0 ? `(${discarded.length})` : ''}
        </button>
        {discardedOpen && (
          <div style={styles.discardedContent}>
            {discardedLoading ? (
              <p style={styles.muted}>Cargando…</p>
            ) : discarded.length === 0 ? (
              <p style={styles.muted}>No hay clientes descartados.</p>
            ) : (
              <table style={styles.table}>
                <thead>
                  <tr style={styles.tr}>
                    <th style={styles.th}>Cliente</th>
                    <th style={styles.th}>Status</th>
                    <th style={styles.th}>team_id</th>
                    <th style={styles.th}></th>
                  </tr>
                </thead>
                <tbody>
                  {discarded.map(d => (
                    <tr key={d.siete_id} style={styles.tr}>
                      <td style={styles.td}>
                        <strong>{d.siete_name}</strong>
                        <div style={styles.slug}>siete_id: {d.siete_id} · slug: {d.siete_slug}</div>
                      </td>
                      <td style={styles.td}>{d.status || '—'}</td>
                      <td style={styles.td}>{d.team_id ?? '—'}</td>
                      <td style={styles.td}>
                        <button
                          type="button"
                          onClick={() => handleRestore(d.siete_id)}
                          style={styles.restoreButton}
                        >
                          Restaurar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: { maxWidth: 900, margin: '40px auto', padding: '0 20px',
                fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
  title: { fontSize: 24, fontWeight: 600, marginBottom: 8, color: '#1a1a1a' },
  subtitle: { color: '#666', marginBottom: 24, fontSize: 14 },
  table: { width: '100%', borderCollapse: 'collapse', marginBottom: 24,
            border: '1px solid #e0e0e0', borderRadius: 6, overflow: 'hidden' },
  tr: { borderBottom: '1px solid #e0e0e0' },
  th: { textAlign: 'left', padding: '12px 14px', background: '#f7f7f7',
         fontSize: 13, fontWeight: 600, color: '#555' },
  td: { padding: '12px 14px', fontSize: 14, verticalAlign: 'top' },
  slug: { fontSize: 11, color: '#999', marginTop: 4 },
  suggestion: { fontSize: 12, color: '#2c7a3e', marginTop: 6 },
  select: { width: '100%', padding: '8px 10px', fontSize: 14,
             border: '1px solid #ccc', borderRadius: 4, background: 'white' },
  manualInput: { width: '100%', padding: '8px 10px', fontSize: 14,
                  border: '1px solid #ccc', borderRadius: 4, marginTop: 6 },
  actions: { display: 'flex', gap: 12, alignItems: 'center' },
  button: { padding: '10px 20px', background: '#2c7a3e', color: 'white',
             border: 'none', borderRadius: 6, fontSize: 14, fontWeight: 500 },
  linkButton: { background: 'none', border: 'none', color: '#666',
                  cursor: 'pointer', fontSize: 13, textDecoration: 'underline' },
  warningCard: { padding: 12, background: '#fff7e0', border: '1px solid #ffd966',
                   borderRadius: 6, marginBottom: 16, fontSize: 14 },
  successCard: { padding: 16, background: '#e8f5e9', border: '1px solid #66bb6a',
                   borderRadius: 6, fontSize: 14, color: '#2e7d32' },
  resultCard: { marginTop: 24, padding: 16, background: '#f5f5f5',
                  borderRadius: 6, fontSize: 14 },
  savedRow: { padding: '4px 0', color: '#2e7d32' },
  errorRow: { padding: '4px 0', color: '#c62828', fontSize: 13 },
  errorText: { color: '#c62828', fontWeight: 500, marginTop: 12 },
  errorCard: { marginTop: 16, padding: 12, background: '#ffebee',
                border: '1px solid #ef9a9a', borderRadius: 6,
                fontSize: 14, color: '#c62828' },
  headerRow: { display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 8 },
  linkAction: { fontSize: 12, color: '#2563eb', textDecoration: 'none',
                  padding: '6px 10px', background: '#eff6ff',
                  border: '1px solid #bfdbfe', borderRadius: 6 },
  discardButton: { padding: '6px 12px', background: 'white',
                     color: '#c62828', border: '1px solid #ef9a9a',
                     borderRadius: 4, cursor: 'pointer', fontSize: 12 },
  restoreButton: { padding: '6px 12px', background: 'white',
                     color: '#2c7a3e', border: '1px solid #66bb6a',
                     borderRadius: 4, cursor: 'pointer', fontSize: 12 },
  discardedSection: { marginTop: 32, paddingTop: 16,
                        borderTop: '1px solid #e0e0e0' },
  discardedToggle: { background: 'none', border: 'none',
                       cursor: 'pointer', fontSize: 14, color: '#555',
                       padding: 0, fontWeight: 500 },
  discardedContent: { marginTop: 12 },
  muted: { color: '#999', fontSize: 13, fontStyle: 'italic' },
}
