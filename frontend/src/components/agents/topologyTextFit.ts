/**
 * Width-aware text fitting for topology SVG labels.
 *
 * Topology labels render inside fixed-size SVG node/group boxes in VIEWBOX
 * units. Because the whole SVG scales as one unit (responsive `width: 100%`
 * and the `fillHeight` fullscreen mode), any fitting must be decided in
 * viewBox coordinates — measuring the live DOM (`getComputedTextLength`)
 * would return post-scale pixels and break under `fillHeight`. So width is
 * ESTIMATED from a per-character em-width table calibrated on the app's UI
 * fonts (Roboto, Helvetica/Arial fallback): every entry slightly
 * over-estimates the real advance width, which guarantees a fitted label
 * always fits inside its box while realistically-fitting labels (e.g. a
 * 19–20 char id-style name) are not truncated unnecessarily.
 */

/** Ellipsis appended to truncated labels. */
export const ELLIPSIS = '…'

/** Options adjusting the width estimate for a specific text style. */
export interface TextFitOptions {
  /** Bold text renders ~6% wider. */
  bold?: boolean
  /** Extra letter-spacing in px per character (SVG `letterSpacing`). */
  letterSpacing?: number
}

/** Result of fitting a label to a maximum width. */
export interface FittedText {
  /** Text to render — the original, or a prefix + ellipsis. */
  text: string
  /** `true` when the label did not fit and was shortened. */
  truncated: boolean
}

/** Narrow glyphs (≈0.3em advance in Roboto/Arial). */
const NARROW_CHARS = new Set(['i', 'l', 'j', 't', '|', '!', '.', ',', ':', ';', "'", '"', '`', 'I'])
/** Medium-narrow glyphs (≈0.4em advance). */
const MEDIUM_CHARS = new Set(['f', 'r', '(', ')', '[', ']', '{', '}', '-', '·', '–', '—', '/'])
/** Wide glyphs (≈0.9em+ advance). */
const WIDE_CHARS = new Set(['m', 'w', 'M', 'W'])

/**
 * Per-character advance width in em units. Values are deliberately at or
 * above the widest of the fallback fonts so the estimate never
 * under-measures a rendered label.
 */
function charEmWidth(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0
  if (NARROW_CHARS.has(ch)) return 0.3
  if (MEDIUM_CHARS.has(ch)) return 0.4
  if (cp === 0x20) return 0.3 // space
  if (ch === '_') return 0.56
  if (ch === ELLIPSIS) return 0.8
  if (ch === '@') return 1.05
  if (WIDE_CHARS.has(ch)) return 0.95
  if (cp >= 0x30 && cp <= 0x39) return 0.58 // 0-9
  if (cp >= 0x41 && cp <= 0x5a) return 0.74 // A-Z
  if (cp >= 0x61 && cp <= 0x7a) return 0.52 // a-z
  // CJK ideographs / kana / Hangul render full-width.
  if ((cp >= 0x2e80 && cp <= 0x9fff) || (cp >= 0xac00 && cp <= 0xd7af)) return 1.0
  // Emoji and other astral symbols.
  if (cp >= 0x1f000) return 1.4
  // Unknown symbols — safe over-estimate.
  return 0.6
}

/**
 * Estimates the rendered advance width of `text` at `fontSize` (SVG user
 * units / viewBox units), honouring bold and letter-spacing.
 */
export function estimateTextWidth(text: string, fontSize: number, options: TextFitOptions = {}): number {
  const chars = Array.from(text)
  const em = chars.reduce((sum, ch) => sum + charEmWidth(ch), 0)
  const base = em * fontSize
  const spacing = (options.letterSpacing ?? 0) * chars.length
  return (options.bold ? base * 1.06 : base) + spacing
}

/**
 * Fits `text` to `maxWidth` (viewBox units at `fontSize`): returns the text
 * unchanged when it fits, otherwise the longest prefix whose width plus the
 * ellipsis still fits (`truncated: true`). When even a single character plus
 * the ellipsis cannot fit, the bare ellipsis is returned so the rendered
 * glyph never exceeds the available width.
 */
export function fitTextToWidth(text: string, maxWidth: number, fontSize: number, options: TextFitOptions = {}): FittedText {
  if (estimateTextWidth(text, fontSize, options) <= maxWidth) {
    return { text, truncated: false }
  }
  const chars = Array.from(text)
  let best = 0
  for (let k = 1; k <= chars.length; k++) {
    const candidate = chars.slice(0, k).join('') + ELLIPSIS
    if (estimateTextWidth(candidate, fontSize, options) <= maxWidth) {
      best = k
    } else {
      break
    }
  }
  return { text: chars.slice(0, best).join('') + ELLIPSIS, truncated: true }
}
