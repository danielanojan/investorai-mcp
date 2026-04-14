import { useState, useRef, useCallback } from 'react'
import type { Citation, TimeRange } from '../types'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  streaming?: boolean
  error?: boolean
}

export function useChat(symbol: string, range: TimeRange) {
  const [messages,   setMessages]   = useState<ChatMessage[]>([])
  const [streaming,  setStreaming]   = useState(false)
  const abortRef                    = useRef<AbortController>()

  const sendMessage = useCallback(async (question: string) => {
    if (!question.trim() || streaming) return

    // Add user message
    const userMsg: ChatMessage = { role: 'user', content: question }
    setMessages(prev => [...prev, userMsg])

    // Add empty assistant message that will be filled by stream
    setMessages(prev => [...prev, {
      role: 'assistant', content: '', streaming: true
    }])
    setStreaming(true)

    // Build history for context (last 10 messages)
    const history = messages.slice(-10).map(m => ({
      role:    m.role,
      content: m.content,
    }))

    abortRef.current = new AbortController()

    try {
      const response = await fetch('/api/chat/stream', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ symbol, question, history, range }),
        signal:  abortRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader  = response.body!.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''
      let   citations: Citation[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          try {
            const event = JSON.parse(raw)

            if (event.type === 'token') {
              setMessages(prev => {
                const updated = [...prev]
                const last    = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + event.content,
                  }
                }
                return updated
              })
            }

            if (event.type === 'citations') {
              citations = event.citations || []
            }

            if (event.type === 'done') {
              setMessages(prev => {
                const updated = [...prev]
                const last    = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    streaming:  false,
                    citations,
                  }
                }
                return updated
              })
            }

            if (event.type === 'error') {
              setMessages(prev => {
                const updated = [...prev]
                const last    = updated[updated.length - 1]
                if (last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content:   event.message || 'Something went wrong.',
                    streaming: false,
                    error:     true,
                  }
                }
                return updated
              })
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return
      setMessages(prev => {
        const updated = [...prev]
        const last    = updated[updated.length - 1]
        if (last?.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content:   'Connection error. Please try again.',
            streaming: false,
            error:     true,
          }
        }
        return updated
      })
    } finally {
      setStreaming(false)
    }
  }, [symbol, range, messages, streaming])

  const clearMessages = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setStreaming(false)
  }, [])

  return { messages, streaming, sendMessage, clearMessages }
}
