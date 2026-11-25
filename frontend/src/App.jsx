import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const ACCESS_KEY = 'eyesight_access_token'
const REFRESH_KEY = 'eyesight_refresh_token'

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem(REFRESH_KEY)
  if (!refreshToken) return null

  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    return null
  }

  const data = await response.json()
  localStorage.setItem(ACCESS_KEY, data.access_token)
  localStorage.setItem(REFRESH_KEY, data.refresh_token)
  return data.access_token
}

// Add the bearer token to API calls and retry once after an expired access token.
async function apiRequest(path, options = {}, retry = true) {
  const token = localStorage.getItem(ACCESS_KEY)
  const headers = new Headers(options.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  let response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (response.status === 401 && retry) {
    const renewed = await refreshAccessToken()
    if (renewed) return apiRequest(path, options, false)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `Request failed (${response.status})`)
  }
  if (response.status === 204) return null
  return response.json()
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function StatusPill({ value }) {
  const normalized = (value || 'unknown').toLowerCase()
  return <span className={`status-pill status-${normalized}`}>{normalized.replaceAll('_', ' ')}</span>
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const endpoint = mode === 'login' ? '/auth/login' : '/auth/signup'
      const body = mode === 'login'
        ? { email, password }
        : { display_name: displayName, email, password }
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || data.message || 'Authentication failed')
      if (mode === 'signup') {
        setMode('login')
        setPassword('')
        setError('Account created. Sign in with your new credentials.')
        return
      }
      localStorage.setItem(ACCESS_KEY, data.access_token)
      localStorage.setItem(REFRESH_KEY, data.refresh_token)
      onAuthenticated()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="brand-mark">E</div>
        <p className="eyebrow">VISUAL ASSISTANCE PLATFORM</p>
        <h1>EyeSight</h1>
        <p className="muted">A clearer view of every captured moment.</p>
        <form onSubmit={submit} className="auth-form">
          {mode === 'signup' && (
            <label>Display name
              <input value={displayName} onChange={e => setDisplayName(e.target.value)} required maxLength={100} />
            </label>
          )}
          <label>Email address
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label>Password
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={mode === 'signup' ? 8 : undefined} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </label>
          {error && <p className="form-message">{error}</p>}
          <button className="primary-button" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
        </form>
        <button className="text-button" onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setError('') }}>
          {mode === 'login' ? 'Create an EyeSight account' : 'Back to sign in'}
        </button>
      </section>
    </main>
  )
}

function Dashboard({ onLogout }) {
  const [profile, setProfile] = useState(null)
  const [sessions, setSessions] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [frames, setFrames] = useState([])
  const [questions, setQuestions] = useState([])
  const [preview, setPreview] = useState('')
  const [connection, setConnection] = useState('connecting')
  const [activeTab, setActiveTab] = useState('overview')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const imageUrls = useRef([])
  const selectedSession = sessions.find(item => item.session_id === selectedId)

  const loadSessions = useCallback(async () => {
    const [me, list] = await Promise.all([
      apiRequest('/auth/me'),
      apiRequest('/api/dashboard/sessions'),
    ])
    setProfile(me)
    setSessions(list)
    setSelectedId(current => current || list[0]?.session_id || null)
  }, [])

  const loadSessionData = useCallback(async (sessionId) => {
    if (!sessionId) {
      setFrames([])
      setQuestions([])
      return
    }
    const [frameRows, questionRows] = await Promise.all([
      apiRequest(`/api/dashboard/sessions/${sessionId}/frames?limit=40`),
      apiRequest(`/api/dashboard/sessions/${sessionId}/questions?limit=30`),
    ])

    // Fetch protected images with the bearer header; object URLs cannot expose storage paths.
    imageUrls.current.forEach(URL.revokeObjectURL)
    imageUrls.current = []
    const withImages = await Promise.all(frameRows.map(async frame => {
      try {
        const token = localStorage.getItem(ACCESS_KEY)
        const response = await fetch(`${API_BASE}${frame.image_url}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok) return { ...frame, preview_url: '' }
        const url = URL.createObjectURL(await response.blob())
        imageUrls.current.push(url)
        return { ...frame, preview_url: url }
      } catch {
        return { ...frame, preview_url: '' }
      }
    }))
    setFrames(withImages)
    setQuestions(questionRows)
  }, [])

  useEffect(() => {
    let mounted = true
    loadSessions()
      .catch(err => { if (mounted) setError(err.message) })
      .finally(() => { if (mounted) setLoading(false) })
    return () => { mounted = false }
  }, [loadSessions])

  useEffect(() => {
    if (!selectedId) return undefined
    let mounted = true
    const update = () => loadSessionData(selectedId).catch(err => { if (mounted) setError(err.message) })
    update()
    const timer = window.setInterval(() => {
      loadSessions().catch(err => { if (mounted) setError(err.message) })
      update()
    }, 7000)
    return () => {
      mounted = false
      window.clearInterval(timer)
      imageUrls.current.forEach(URL.revokeObjectURL)
      imageUrls.current = []
    }
  }, [selectedId, loadSessionData, loadSessions])

  // The dashboard viewer receives JPEG binary messages from the existing WebSocket route.
  useEffect(() => {
    if (!selectedId || !selectedSession || !['starting', 'active'].includes(selectedSession.status)) {
      setConnection('offline')
      setPreview('')
      return undefined
    }
    const token = localStorage.getItem(ACCESS_KEY)
    const socketUrl = API_BASE.replace(/^http/, 'ws')
    const socket = new WebSocket(`${socketUrl}/ws/webrtc/${selectedId}/watch?token=${encodeURIComponent(token || '')}`)
    socket.binaryType = 'blob'
    socket.onopen = () => setConnection('connected')
    socket.onmessage = event => {
      if (event.data instanceof Blob) {
        const url = URL.createObjectURL(event.data)
        setPreview(previous => {
          if (previous) URL.revokeObjectURL(previous)
          return url
        })
      }
    }
    socket.onerror = () => setConnection('unavailable')
    socket.onclose = () => setConnection('offline')
    return () => {
      socket.close()
      setPreview(previous => {
        if (previous) URL.revokeObjectURL(previous)
        return ''
      })
    }
  }, [selectedId, selectedSession?.status])

  async function logout() {
    const refreshToken = localStorage.getItem(REFRESH_KEY)
    try {
      if (refreshToken) await apiRequest('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    } catch {
      // Clear local credentials even if the network is unavailable.
    }
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    onLogout()
  }

  if (loading) return <main className="loading-screen">Loading EyeSight…</main>

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><span className="brand-mark small">E</span><span>EyeSight</span></div>
        <p className="sidebar-label">WORKSPACE</p>
        {[
          ['overview', 'Overview', '◫'],
          ['frames', 'Frame gallery', '▧'],
          ['questions', 'Questions & answers', '◌'],
        ].map(([key, label, symbol]) => (
          <button key={key} className={`nav-item ${activeTab === key ? 'selected' : ''}`} onClick={() => setActiveTab(key)}>
            <span>{symbol}</span>{label}
          </button>
        ))}
        <div className="sidebar-bottom">
          <div className="profile-mini"><div className="avatar">{profile?.display_name?.[0] || 'U'}</div><div><strong>{profile?.display_name || 'User'}</strong><small>{profile?.email}</small></div></div>
          <button className="text-button logout-button" onClick={logout}>Sign out</button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div><p className="eyebrow">EYESIGHT / DASHBOARD</p><h1>{activeTab === 'overview' ? 'Overview' : activeTab === 'frames' ? 'Frame gallery' : 'Questions & answers'}</h1></div>
          <div className="topbar-right"><span className="live-indicator"><i /> Secure workspace</span><button className="icon-button" onClick={() => loadSessions().catch(err => setError(err.message))} aria-label="Refresh">↻</button></div>
        </header>
        {error && <div className="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}

        <section className="session-toolbar">
          <div><span className="eyebrow">CAPTURE SESSION</span><strong>{selectedSession ? `Session #${selectedSession.session_id}` : 'No sessions yet'}</strong></div>
          <select value={selectedId || ''} onChange={e => setSelectedId(Number(e.target.value) || null)}>
            <option value="">Select a session</option>
            {sessions.map(session => <option key={session.session_id} value={session.session_id}>#{session.session_id} · {formatDate(session.started_at)}</option>)}
          </select>
        </section>

        {!selectedSession ? (
          <section className="empty-state"><div className="empty-icon">◉</div><h2>No capture sessions found</h2><p>When the mobile app starts a session, its status, camera preview, frames, and questions will appear here.</p></section>
        ) : activeTab === 'overview' ? (
          <>
            <section className="stats-grid">
              <article className="stat-card"><span>SESSION STATUS</span><StatusPill value={selectedSession.status} /><small>Lifecycle state</small></article>
              <article className="stat-card"><span>CAMERA STREAM</span><StatusPill value={selectedSession.stream_status} /><small>WebRTC connection</small></article>
              <article className="stat-card"><span>CAPTURED FRAMES</span><strong>{frames.length}</strong><small>Unexpired history frames</small></article>
              <article className="stat-card"><span>QUESTIONS</span><strong>{questions.length}</strong><small>Conversation records</small></article>
            </section>
            <section className="overview-grid">
              <article className="panel preview-panel">
                <div className="panel-heading"><div><span className="eyebrow">LIVE CAMERA</span><h2>Live preview</h2></div><StatusPill value={connection} /></div>
                {preview ? <img className="live-preview" src={preview} alt="Live camera preview" /> : <div className="preview-placeholder"><span>◉</span><strong>Live preview unavailable</strong><small>Open the mobile camera session to start streaming.</small></div>}
                <div className="preview-meta"><span>Device: {selectedSession.device?.device_name || 'Unknown device'}</span><span>{selectedSession.device?.platform || '—'}</span></div>
              </article>
              <article className="panel session-panel">
                <div className="panel-heading"><div><span className="eyebrow">SESSION DETAILS</span><h2>Capture information</h2></div></div>
                <dl className="details-list">
                  <div><dt>Started</dt><dd>{formatDate(selectedSession.started_at)}</dd></div>
                  <div><dt>Last heartbeat</dt><dd>{formatDate(selectedSession.last_heartbeat_at)}</dd></div>
                  <div><dt>Language</dt><dd>{selectedSession.language_code?.toUpperCase()}</dd></div>
                  <div><dt>Device</dt><dd>{selectedSession.device?.device_name || '—'}</dd></div>
                  <div><dt>Platform</dt><dd>{selectedSession.device?.platform || '—'}</dd></div>
                  <div><dt>History expires</dt><dd>{formatDate(selectedSession.history_expires_at)}</dd></div>
                </dl>
              </article>
            </section>
            <FrameStrip frames={frames.slice(0, 4)} onViewAll={() => setActiveTab('frames')} />
            <QuestionStrip questions={questions.slice(0, 3)} onViewAll={() => setActiveTab('questions')} />
          </>
        ) : activeTab === 'frames' ? (
          <section className="panel">
            <div className="panel-heading"><div><span className="eyebrow">VISUAL HISTORY</span><h2>Processed frames</h2></div><span className="muted">{frames.length} shown</span></div>
            {frames.length === 0 ? <p className="empty-inline">No frames have been saved for this session yet.</p> : <div className="frame-grid">{frames.map(frame => <FrameCard key={frame.frame_id} frame={frame} />)}</div>}
          </section>
        ) : (
          <section className="panel">
            <div className="panel-heading"><div><span className="eyebrow">CONVERSATION HISTORY</span><h2>Questions and answers</h2></div><span className="muted">{questions.length} shown</span></div>
            {questions.length === 0 ? <p className="empty-inline">No questions have been recorded for this session.</p> : <div className="question-list">{questions.map(question => <QuestionCard key={question.question_id} question={question} />)}</div>}
          </section>
        )}
      </main>
    </div>
  )
}

function FrameStrip({ frames, onViewAll }) {
  return <section className="panel compact-panel"><div className="panel-heading"><div><span className="eyebrow">RECENT VISUALS</span><h2>Latest frames</h2></div><button className="text-button" onClick={onViewAll}>View all →</button></div>{frames.length ? <div className="recent-frames">{frames.map(frame => <div className="recent-frame" key={frame.frame_id}>{frame.preview_url ? <img src={frame.preview_url} alt={`Frame ${frame.frame_id}`} /> : <div className="image-fallback">◫</div>}<div><strong>Frame #{frame.sequence_number}</strong><small>{formatDate(frame.captured_at)}</small><StatusPill value={frame.processing_status} /></div></div>)}</div> : <p className="empty-inline">Frames will appear here when the camera is capturing.</p>}</section>
}

function FrameCard({ frame }) {
  return <article className="frame-card">
    {frame.preview_url ? <img src={frame.preview_url} alt={`Captured frame ${frame.sequence_number}`} /> : <div className="image-fallback large">◫</div>}
    <div className="frame-card-body"><div className="frame-card-title"><strong>Frame #{frame.sequence_number}</strong><StatusPill value={frame.processing_status} /></div><small>{formatDate(frame.captured_at)}</small>
      <div className="quality-row"><span>Sharpness <b>{Number(frame.sharpness_score).toFixed(1)}</b></span><span>Brightness <b>{Number(frame.brightness_score).toFixed(1)}</b></span></div>
      {frame.objects?.length > 0 && <div className="tag-list">{frame.objects.map((item, i) => <span key={i}>{item.label} {Math.round(item.confidence * 100)}%</span>)}</div>}
      {frame.ocr?.length > 0 && <div className="ocr-preview"><b>Detected text</b><p>{frame.ocr.map(item => item.text).join(' · ')}</p></div>}
    </div>
  </article>
}

function QuestionStrip({ questions, onViewAll }) {
  return <section className="panel compact-panel"><div className="panel-heading"><div><span className="eyebrow">ASSISTANT ACTIVITY</span><h2>Recent questions</h2></div><button className="text-button" onClick={onViewAll}>View all →</button></div>{questions.length ? <div className="question-list">{questions.map(question => <QuestionCard key={question.question_id} question={question} />)}</div> : <p className="empty-inline">Questions asked during a session will appear here.</p>}</section>
}

function QuestionCard({ question }) {
  return <article className="question-card"><div className="question-dot">Q</div><div className="question-content"><div className="question-meta"><strong>{question.input_type === 'voice' ? 'Voice question' : 'Text question'}</strong><small>{formatDate(question.received_at)}</small><StatusPill value={question.status} /></div><p className="question-text">{question.question_text || 'Waiting for voice transcription…'}</p>{question.answer && <div className="answer-block"><b>EyeSight answer</b><p>{question.answer.answer_text}</p><small>{question.answer.answer_type.replaceAll('_', ' ')} · {question.evidence?.length || 0} supporting frames</small></div>}</div></article>
}

function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem(ACCESS_KEY)))
  return authenticated
    ? <Dashboard onLogout={() => setAuthenticated(false)} />
    : <AuthScreen onAuthenticated={() => setAuthenticated(true)} />
}

export default App
