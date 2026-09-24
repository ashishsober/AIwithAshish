import { useState } from 'react'
import './App.css'

function App() {
  const [prompt, setPrompt] = useState('Summarize the goals of this project in one paragraph.')
  const [response, setResponse] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event) {
    event.preventDefault()

    if (!prompt.trim()) {
      setError('Please enter a prompt.')
      return
    }

    setLoading(true)
    setError('')
    setResponse('')

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt }),
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.error || 'Request failed.')
      }

      setResponse(data.response || '')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <div className="chat-card">
        <h1>Qwen Chat</h1>
        <p className="subtitle">Send a prompt to the local Qwen model.</p>

        <form onSubmit={handleSubmit} className="chat-form">
          <label htmlFor="prompt">Prompt</label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Paste context or ask a question..."
            rows="8"
          />

          <button type="submit" disabled={loading}>
            {loading ? 'Sending...' : 'Send to Qwen'}
          </button>
        </form>

        {error && <div className="message error">{error}</div>}

        {response && (
          <div className="message success">
            <strong>Response:</strong>
            <p>{response}</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
