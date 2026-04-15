import { useState, useEffect, useRef } from 'react'
import { Send, Trash2, Bot, User, Key } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useChat } from '../hooks/useChat'
import { useBYOK } from '../hooks/useBYOK'
import BYOKSetup from './BYOKSetup'
import type { TimeRange } from '../types'
import type { ChatMessage } from '../hooks/useChat'

interface Props {
  symbol: string
  range:  TimeRange
}

function CitationBadge({ citation }: { citation: any }) {
  if (citation.type === 'db') {
    return (
      <span className="inline-flex items-center text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded border border-blue-100">
        DB · {citation.date}
      </span>
    )
  }
  if (citation.type === 'news' && citation.url) {
    return (
      <a
        href={citation.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center text-xs bg-gray-50 text-gray-600 px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100"
      >
        {citation.publisher} ↗
      </a>
    )
  }
  return null
}

function Message({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-blue-600' : 'bg-gray-100'
      }`}>
        {isUser
          ? <User size={14} className="text-white" />
          : <Bot  size={14} className="text-gray-500" />
        }
      </div>
      <div className={`max-w-[80%] flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : message.error
            ? 'bg-red-50 text-red-700 border border-red-200 rounded-tl-sm'
            : 'bg-white text-gray-800 border border-gray-200 rounded-tl-sm shadow-sm'
        }`}>
          {message.content
            ? isUser
              ? message.content
              : <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1"><ReactMarkdown>{message.content}</ReactMarkdown></div>
            : message.streaming && (
              <span className="flex gap-1 items-center py-0.5">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            )}
        </div>
        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1 px-1">
            {message.citations.map((c, i) => (
              <CitationBadge key={i} citation={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const SUGGESTIONS = [
  "How has this stock performed this year?",
  "What is the 52-week high and low?",
  "How volatile is this stock?",
  "What is the latest news?",
]

export default function ChatPanel({ symbol, range }: Props) {
  const byok                        = useBYOK()
  const [showSetup, setShowSetup]   = useState(false)
  const [input, setInput]           = useState('')
  const { messages, streaming, sendMessage, clearMessages } = useChat(
    symbol, range, byok.apiKey
  )
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || streaming || !byok.isSet) return
    const q = input.trim()
    setInput('')
    await sendMessage(q)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <>
      {showSetup && (
        <BYOKSetup
          onSave={(key, model) => byok.setKey(key, model)}
          onClose={() => setShowSetup(false)}
        />
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col h-[500px]">

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Bot size={16} className="text-blue-600" />
            <span className="text-sm font-semibold text-gray-800">
              Ask about {symbol}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {byok.isSet ? (
              <button
                onClick={() => byok.clearKey()}
                className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
                title="Clear API key"
              >
                <Key size={12} />
                {byok.provider}
              </button>
            ) : (
              <button
                onClick={() => setShowSetup(true)}
                className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1 font-medium"
              >
                <Key size={12} />
                Set API key
              </button>
            )}
            {messages.length > 0 && (
              <button
                onClick={clearMessages}
                className="text-gray-400 hover:text-gray-600"
                title="Clear chat"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">

          {/* No API key state */}
          {!byok.isSet && (
            <div className="h-full flex flex-col items-center justify-center gap-4 text-center">
              <div className="w-12 h-12 bg-blue-50 rounded-full flex items-center justify-center">
                <Key size={22} className="text-blue-600" />
              </div>
              <div>
                <p className="text-sm font-medium text-gray-800">
                  Provide your API key to start chatting
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Works with Anthropic, OpenAI, and Groq.
                  Your key stays in this browser tab only.
                </p>
              </div>
              <button
                onClick={() => setShowSetup(true)}
                className="bg-blue-600 text-white text-sm font-medium px-5 py-2.5 rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
              >
                <Key size={15} />
                Set up API key
              </button>
            </div>
          )}

          {/* Key set — empty state */}
          {byok.isSet && messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center gap-4">
              <p className="text-sm text-gray-400 text-center">
                Ask anything about {symbol} — all answers are grounded to real data.
              </p>
              <div className="flex flex-col gap-2 w-full">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => { setInput(s); inputRef.current?.focus() }}
                    className="text-left text-xs text-gray-500 bg-gray-50 hover:bg-gray-100 px-3 py-2 rounded-lg border border-gray-200 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Messages */}
          {messages.map((msg, i) => (
            <Message key={i} message={msg} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-4 py-3 border-t border-gray-100">
          {!byok.isSet ? (
            <button
              onClick={() => setShowSetup(true)}
              className="w-full py-2.5 text-sm font-medium text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors border border-blue-100 flex items-center justify-center gap-2"
            >
              <Key size={15} />
              Set up API key to enable chat
            </button>
          ) : (
            <>
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={streaming ? 'Generating...' : `Ask about ${symbol}...`}
                  disabled={streaming}
                  className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || streaming}
                  className="bg-blue-600 text-white rounded-lg px-3 py-2 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={16} />
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1.5">
                All responses verified against real price data.
              </p>
            </>
          )}
        </div>

      </div>
    </>
  )
}
