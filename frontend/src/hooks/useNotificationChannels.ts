import { useState, useEffect, useCallback } from 'react'
import { listChannels } from '../services/notificationService'
import type { NotificationChannel } from '../types'

export function useNotificationChannels() {
  const [channels, setChannels] = useState<NotificationChannel[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await listChannels()
      setChannels(data)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetch()
  }, [fetch])

  return { channels, isLoading, error, refetch: fetch }
}
