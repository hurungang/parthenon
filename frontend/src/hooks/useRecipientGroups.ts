import { useState, useEffect, useCallback } from 'react'
import { listRecipientGroups } from '../services/notificationService'
import type { RecipientGroup } from '../types'

export function useRecipientGroups(limit?: number, offset?: number) {
  const [groups, setGroups] = useState<RecipientGroup[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await listRecipientGroups(limit != null ? { limit, offset } : undefined)
      setGroups(data)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [limit, offset])

  useEffect(() => {
    void fetch()
  }, [fetch])

  return { groups, isLoading, error, refetch: fetch }
}
