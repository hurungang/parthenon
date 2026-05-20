import { useState, useEffect, useCallback } from 'react'
import { listRecipientGroups } from '../services/notificationService'
import type { RecipientGroup } from '../types'

export function useRecipientGroups() {
  const [groups, setGroups] = useState<RecipientGroup[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await listRecipientGroups()
      setGroups(data)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetch()
  }, [fetch])

  return { groups, isLoading, error, refetch: fetch }
}
