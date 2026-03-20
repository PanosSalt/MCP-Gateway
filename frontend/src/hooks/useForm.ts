import { useState } from 'react'

export function useForm<T extends Record<string, unknown>>(initial: T) {
  const [form, setForm] = useState<T>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const setField = <K extends keyof T>(k: K, v: T[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const reset = () => {
    setForm(initial)
    setError('')
    setSuccess('')
  }

  return { form, setForm, setField, busy, setBusy, error, setError, success, setSuccess, reset }
}
