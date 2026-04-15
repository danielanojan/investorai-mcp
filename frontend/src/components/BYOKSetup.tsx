/**
 * BYOK setup modal.
 * API key stored in sessionStorage only — never persisted to server.
 * Clears automatically when browser tab closes.
 */
import { useState } from 'react'
import { Key, Eye, EyeOff, CheckCircle, XCircle, Loader } from 'lucide-react'
import type { LLMProvider } from '../hooks/useBYOK'

interface Props {
  onSave:  (apiKey: string, model: string) => void
  onClose: () => void
}

interface ProviderConfig {
  label:       string
  placeholder: string
  models:      { value: string; label: string }[]
  docsUrl:     string
  keyPrefix:   string
}

const PROVIDERS: Record<LLMProvider, ProviderConfig> = {
  anthropic: {
    label:       'Anthropic',
    placeholder: 'sk-ant-api03-...',
    keyPrefix:   'sk-ant',
    docsUrl:     'https://console.anthropic.com',
    models: [
      { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4 (recommended)' },
      { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (faster)' },
    ],
  },
  openai: {
    label:       'OpenAI',
    placeholder: 'sk-proj-...',
    keyPrefix:   'sk-',
    docsUrl:     'https://platform.openai.com/api-keys',
    models: [
      { value: 'gpt-4o',      label: 'GPT-4o (recommended)' },
      { value: 'gpt-4o-mini', label: 'GPT-4o Mini (faster)' },
    ],
  },
  groq: {
    label:       'Groq',
    placeholder: 'gsk_...',
    keyPrefix:   'gsk_',
    docsUrl:     'https://console.groq.com/keys',
    models: [
      { value: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B (recommended)' },
      { value: 'mixtral-8x7b-32768',      label: 'Mixtral 8x7B (faster)' },
    ],
  },
}

type ValidationState = 'idle' | 'loading' | 'success' | 'error'

export default function BYOKSetup({ onSave, onClose }: Props) {
  const [provider,   setProvider]   = useState<LLMProvider>('anthropic')
  const [apiKey,     setApiKey]     = useState('')
  const [model,      setModel]      = useState(PROVIDERS.anthropic.models[0].value)
  const [showKey,    setShowKey]    = useState(false)
  const [validation, setValidation] = useState<ValidationState>('idle')
  const [errorMsg,   setErrorMsg]   = useState('')

  const config = PROVIDERS[provider]

  const handleProviderChange = (p: LLMProvider) => {
    setProvider(p)
    setModel(PROVIDERS[p].models[0].value)
    setApiKey('')
    setValidation('idle')
    setErrorMsg('')
  }

  const handleValidate = async () => {
    if (!apiKey.trim()) return
    setValidation('loading')
    setErrorMsg('')

    try {
      const res = await fetch('/api/llm/validate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ api_key: apiKey.trim(), model }),
      })
      const data = await res.json()

      if (res.ok && data.valid) {
        setValidation('success')
      } else {
        setValidation('error')
        setErrorMsg(data.error?.message || 'Invalid API key')
      }
    } catch {
      setValidation('error')
      setErrorMsg('Could not reach the server. Please try again.')
    }
  }

  const handleSave = () => {
    if (!apiKey.trim() || validation !== 'success') return
    onSave(apiKey.trim(), model)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">

        {/* Header */}
        <div className="px-6 py-5 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-blue-50 rounded-full flex items-center justify-center">
              <Key size={18} className="text-blue-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                Set up your API key
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Your key stays in this browser tab only — never stored on our servers
              </p>
            </div>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5">

          {/* Provider selector */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-2">
              Provider
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(Object.keys(PROVIDERS) as LLMProvider[]).map(p => (
                <button
                  key={p}
                  onClick={() => handleProviderChange(p)}
                  className={`py-2 px-3 rounded-lg text-sm font-medium border transition-colors ${
                    provider === p
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
                  }`}
                >
                  {PROVIDERS[p].label}
                </button>
              ))}
            </div>
          </div>

          {/* Model selector */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-2">
              Model
            </label>
            <select
              value={model}
              onChange={e => setModel(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 outline-none focus:ring-2 focus:ring-blue-500"
            >
              {config.models.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* API key input */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-gray-700">
                API Key
              </label>
              <a
                href={config.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 hover:underline"
              >
                Get a key →
              </a>
            </div>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => { setApiKey(e.target.value); setValidation('idle') }}
                placeholder={config.placeholder}
                className={`w-full border rounded-lg px-3 py-2 pr-10 text-sm outline-none focus:ring-2 focus:ring-blue-500 font-mono ${
                  validation === 'error'
                    ? 'border-red-300 bg-red-50'
                    : validation === 'success'
                    ? 'border-green-300 bg-green-50'
                    : 'border-gray-200'
                }`}
              />
              <button
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>

            {/* Validation feedback */}
            {validation === 'error' && (
              <div className="flex items-center gap-1.5 mt-1.5">
                <XCircle size={13} className="text-red-500 flex-shrink-0" />
                <p className="text-xs text-red-600">{errorMsg}</p>
              </div>
            )}
            {validation === 'success' && (
              <div className="flex items-center gap-1.5 mt-1.5">
                <CheckCircle size={13} className="text-green-500 flex-shrink-0" />
                <p className="text-xs text-green-600">
                  Key validated successfully
                </p>
              </div>
            )}
          </div>

          {/* Security note */}
          <div className="bg-amber-50 border border-amber-100 rounded-lg px-3 py-2.5">
            <p className="text-xs text-amber-700 leading-relaxed">
              🔒 Your API key is stored in <strong>sessionStorage</strong> only.
              It is never sent to our servers or stored in any database.
              It will be automatically cleared when you close this tab.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2 px-4 text-sm font-medium text-gray-600 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={validation === 'success' ? handleSave : handleValidate}
            disabled={!apiKey.trim() || validation === 'loading'}
            className="flex-1 py-2 px-4 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            {validation === 'loading' ? (
              <>
                <Loader size={14} className="animate-spin" />
                Validating...
              </>
            ) : validation === 'success' ? (
              <>
                <CheckCircle size={14} />
                Save & Enable Chat
              </>
            ) : (
              'Validate Key'
            )}
          </button>
        </div>

      </div>
    </div>
  )
}
