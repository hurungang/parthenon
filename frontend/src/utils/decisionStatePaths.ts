/**
 * Shared state-path extraction for decision tool authoring.
 *
 * Question instructions may reference the decision state inline using
 * backtick-quoted paths (e.g. `input.tier`). Those paths are surfaced as
 * suggested state-preset mappings in the authoring form.
 */
const STATE_PATH_PATTERN = /`([^`]+)`/g

/** Extract unique backtick-quoted state paths from instruction text. */
export function detectStatePlaceholders(text: string): string[] {
  if (!text) return []
  const found: string[] = []
  for (const match of text.matchAll(STATE_PATH_PATTERN)) {
    const path = match[1].trim()
    if (path && !found.includes(path)) found.push(path)
  }
  return found
}

/**
 * Extract state paths across a set of question instructions.
 * Returns paths in first-seen order.
 */
export function detectStatePlaceholdersFromQuestions(
  instructions: (string | null | undefined)[],
): string[] {
  const found: string[] = []
  for (const text of instructions) {
    for (const path of detectStatePlaceholders(text ?? '')) {
      if (!found.includes(path)) found.push(path)
    }
  }
  return found
}

/** An explicit state mapping: state key → input property. */
export interface StateMappingRow {
  state_key: string
  key: string
}

export interface ResolvedStateMapping {
  /** Placeholder → input property, resolved automatically (user asked NOTHING). */
  matched: Record<string, string>
  /** Placeholders with no same-named input property — the UI must ask the user to map them. */
  unmatched: string[]
}

/**
 * Auto-match contract (mirrors backend ``resolve_state_mapping``):
 *
 * State keys are the placeholders the tool's prompt/questions use
 * (backtick-quoted paths in instructions) plus explicit preset keys.
 * An explicit mapping wins (rename); otherwise a key resolves 1:1 —
 * the same default an empty preset applies at execution time. A key
 * whose resolved input property is a field of the input data type is
 * MATCHED (silent); anything else is UNMATCHED and needs a user-chosen
 * mapping.
 */
export function resolveStateMapping(
  placeholders: string[],
  explicitMappings: StateMappingRow[],
  inputFieldNames: string[],
): ResolvedStateMapping {
  const keys: string[] = []
  for (const m of explicitMappings) {
    const k = m.state_key.trim()
    if (k && !keys.includes(k)) keys.push(k)
  }
  for (const p of placeholders) {
    const k = (p ?? '').trim()
    if (k && !keys.includes(k)) keys.push(k)
  }
  const fields = new Set(inputFieldNames.filter((f) => f))
  const matched: Record<string, string> = {}
  const unmatched: string[] = []
  for (const key of keys) {
    const explicit = explicitMappings.find((m) => m.state_key.trim() === key)
    const resolved = explicit?.key.trim() || key
    if (fields.has(resolved)) matched[key] = resolved
    else unmatched.push(key)
  }
  return { matched, unmatched }
}
