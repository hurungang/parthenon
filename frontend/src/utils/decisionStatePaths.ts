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
