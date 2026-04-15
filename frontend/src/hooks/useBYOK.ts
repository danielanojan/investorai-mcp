/**
 * BYOK (Bring Your Own Key) hook.
 * Stores the API key in sessionStorage only — never sent to server as a stored value.
 * Key is cleared automatically when the browser tab closes.
 */
import { useState, useCallback } from 'react'

const SESSION_KEY = 'investorai_llm_key'
const MODEL_KEY   = 'investorai_llm_model'

export type LLMProvider = 'anthropic' | 'openai' | 'groq'

export interface BYOKState {
  apiKey:    string | null
  model:     string | null
  provider:  LLMProvider | null
  isSet:     boolean
}

export function useBYOK() {
  const [state, setState] = useState<BYOKState>(() => {
    const key   = sessionStorage.getItem(SESSION_KEY)
    const model = sessionStorage.getItem(MODEL_KEY)
    return {
      apiKey:   key,
      model:    model,
      provider: model ? _inferProvider(model) : null,
      isSet:    !!key,
    }
  })

  const setKey = useCallback((apiKey: string, model: string) => {
    sessionStorage.setItem(SESSION_KEY, apiKey)
    sessionStorage.setItem(MODEL_KEY, model)
    setState({
      apiKey,
      model,
      provider: _inferProvider(model),
      isSet:    true,
    })
  }, [])

  const clearKey = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    sessionStorage.removeItem(MODEL_KEY)
    setState({ apiKey: null, model: null, provider: null, isSet: false })
  }, [])

  return { ...state, setKey, clearKey }
}

function _inferProvider(model: string): LLMProvider {
  if (model.startsWith('claude'))  return 'anthropic'
  if (model.startsWith('gpt'))     return 'openai'
  if (model.startsWith('llama') || model.startsWith('mixtral')) return 'groq'
  return 'anthropic'
}
