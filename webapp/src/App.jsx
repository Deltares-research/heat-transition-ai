import { useRef, useState } from 'react'
import './App.css'

const LOGOS = [
  { src: '/logos/NWN_logo_color_RGB.png', alt: 'NWN' },
  { src: '/logos/TNO_logo.png', alt: 'TNO' },
  {
    src: '/logos/png-clipart-deltares-logo-delft-brand-font-blue-text.png',
    alt: 'Deltares',
  },
]

function formatArgs(args) {
  if (!args || Object.keys(args).length === 0) return ''
  return JSON.stringify(args)
}

function formatResult(result) {
  if (result === null || result === undefined) return ''
  const text = typeof result === 'string' ? result : JSON.stringify(result)
  return text.length > 160 ? `${text.slice(0, 160)}…` : text
}

function Trace({ reasoningSteps, toolCalls }) {
  if (!reasoningSteps?.length && !toolCalls?.length) return null
  return (
    <div className="trace">
      {reasoningSteps?.map((step, i) => (
        <div className="step" key={`r-${i}`}>
          {step}
        </div>
      ))}
      {toolCalls?.map((call, i) => (
        <div className="tool-call" key={`t-${i}`}>
          → {call.name}({formatArgs(call.arguments)}){' '}
          {call.result !== undefined && call.result !== null
            ? `→ ${formatResult(call.result)}`
            : ''}
        </div>
      ))}
    </div>
  )
}

function References({ references }) {
  if (!references?.length) return null
  return (
    <div className="references">
      <div className="references-label">Sources</div>
      {references.map((ref, i) => (
        <div className="reference" key={`${ref.doc_id}-${ref.chunk_id}-${i}`}>
          [{i + 1}] {ref.title || ref.doc_id}{' '}
          <span className="reference-chunk">({ref.chunk_id})</span>
          {ref.quote && <div className="reference-quote">“{ref.quote}”</div>}
        </div>
      ))}
    </div>
  )
}

function Message({ message }) {
  const role = message.role
  return (
    <div className={`message-row ${role}`}>
      <div className="bubble">
        {role === 'assistant' && (
          <Trace
            reasoningSteps={message.reasoningSteps}
            toolCalls={message.toolCalls}
          />
        )}
        {message.pending ? (
          <span className="thinking">thinking…</span>
        ) : (
          message.text
        )}
        {role === 'assistant' && (
          <References references={message.references} />
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const chatRef = useRef(null)

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight })
    })
  }

  const send = async () => {
    const prompt = input.trim()
    if (!prompt || busy) return

    setInput('')
    setBusy(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', text: prompt },
      { role: 'assistant', pending: true },
    ])
    scrollToBottom()

    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const data = await res.json().catch(() => null)

      if (!res.ok) {
        const detail = data?.detail || res.statusText
        setMessages((prev) => [
          ...prev.slice(0, -1),
          { role: 'error', text: detail },
        ])
      } else {
        setMessages((prev) => [
          ...prev.slice(0, -1),
          {
            role: 'assistant',
            text: data.agent_response,
            reasoningSteps: data.reasoning_steps,
            toolCalls: data.tool_calls,
            references: data.references,
          },
        ])
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: 'error', text: `Could not reach the agent: ${err.message}` },
      ])
    } finally {
      setBusy(false)
      scrollToBottom()
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Heat Transition AI</h1>
        <div className="logos">
          {LOGOS.map((logo) => (
            <img src={logo.src} alt={logo.alt} key={logo.src} />
          ))}
        </div>
      </header>

      <div className="chat" ref={chatRef}>
        {messages.length === 0 && (
          <div className="empty-state">
            What do you want to know about the Dutch heat transition?
          </div>
        )}
        {messages.map((message, i) => (
          <Message message={message} key={i} />
        ))}
      </div>

      <div className="composer">
        <textarea
          rows={1}
          value={input}
          placeholder="Ask the agent…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" onClick={send} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  )
}
