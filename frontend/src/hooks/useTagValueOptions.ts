import { useTagDefinitions } from './usePermissions'

/**
 * Returns the list of allowed string values for the given tag key.
 * Returns an empty array when tagKey is null or the tag definition is not found.
 */
export function useTagValueOptions(tagKey: string | null): string[] {
  const { data: tags } = useTagDefinitions()
  if (!tagKey || !tags) return []
  const def = tags.find((t) => t.key === tagKey)
  return def ? def.allowed_values.map((v) => v.value) : []
}
