import { useMemo, useState } from 'react'
import { Alert, Box, Chip, CircularProgress, Collapse, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { AgentOutputType, AgentDataType } from '../../types'
import { useDataType } from '../../hooks/useDataTypes'
import { TypedOutputRenderer } from './TypedOutputRenderer'
import { ContentRenderer } from '../ContentRenderer'
import { MaximizableContent } from '../MaximizableContent'
import { simpleMarkdownToHtml, escapeHtml } from '../../utils/markdown'

// ── Props ─────────────────────────────────────────────────────────────────────

interface OutputTypeResultTabProps {
  outputType: AgentOutputType
  outputData: Record<string, unknown> | null
  outputSchema?: Record<string, unknown> | null
  /** When set, the typed output uses a data type schema for structured rendering */
  dataTypeId?: string | null
  /** Pre-resolved schema — if not provided, component will fetch by dataTypeId */
  dataTypeSchema?: AgentDataType | null
  /** Validation status for typed outputs (from AgentOutput.validation_status) */
  validationStatus?: 'valid' | 'validation_error' | null
  /** Raw output text fallback for validation errors */
  rawOutput?: string | null
  /** Data type display name (for badge) */
  dataTypeName?: string | null
}

// ── Badge config ──────────────────────────────────────────────────────────────

interface BadgeStyle {
  label: string
  bg: string
  color: string
}

function badgeForType(
  outputType: AgentOutputType,
  t: TFunction,
  dataTypeName?: string | null,
): BadgeStyle {
  if (outputType === 'typed' && dataTypeName) {
    return {
      label: dataTypeName,
      bg: '#DBEAFE',
      color: '#1D4ED8',
    }
  }
  switch (outputType) {
    case 'markdown':
      return { label: t('agents.agentType.outputMarkdown', { defaultValue: 'Markdown' }), bg: '#EDE9FE', color: '#7C3AED' }
    case 'typed':
      return { label: t('agents.agentType.outputTyped', { defaultValue: 'Typed' }), bg: '#DBEAFE', color: '#1D4ED8' }
    case 'auto':
    default:
      return { label: t('agents.agentType.outputAuto', { defaultValue: 'Auto' }), bg: '#DCFCE7', color: '#15803D' }
  }
}

// ── JSON tree renderer (recursive, deterministic IDs) ─────────────────────────

let jsonNodeCounter = 0

function renderJsonValue(value: unknown, depth: number, path: string): string {
  const indent = depth * 20

  if (value === null) {
    return `<span class="ojt-null">null</span>`
  }
  if (typeof value === 'boolean') {
    return `<span class="ojt-bool">${value}</span>`
  }
  if (typeof value === 'number') {
    return `<span class="ojt-num">${value}</span>`
  }
  if (typeof value === 'string') {
    return `<span class="ojt-str">"${escapeHtml(value)}"</span>`
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return `<span class="ojt-bracket">[]</span>`
    const nodeId = `ojt_${path.replace(/[^a-zA-Z0-9]/g, '_')}_${jsonNodeCounter++}`
    let html = `<span class="ojt-toggle" onclick="document.getElementById('${nodeId}').classList.toggle('ojt-hidden');this.classList.toggle('ojt-collapsed')" style="cursor:pointer;user-select:none;display:inline-block;width:18px;color:#94A3B8;text-align:center;font-size:12px;flex-shrink:0">▼</span>`
    html += `<span class="ojt-bracket">[</span>`
    html += `<span class="ojt-block" id="${nodeId}">`
    value.forEach((item, i) => {
      html += `<div class="ojt-line" style="padding-left:${indent + 20}px">`
      html += renderJsonValue(item, depth + 1, `${path}[${i}]`)
      if (i < value.length - 1) html += `<span class="ojt-comma">,</span>`
      html += `</div>`
    })
    html += `</span>`
    html += `<span class="ojt-bracket">]</span>`
    return html
  }
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const keys = Object.keys(obj)
    if (keys.length === 0) return `<span class="ojt-bracket">{}</span>`
    const nodeId = `ojt_${path.replace(/[^a-zA-Z0-9]/g, '_')}_${jsonNodeCounter++}`
    let html = `<span class="ojt-toggle" onclick="document.getElementById('${nodeId}').classList.toggle('ojt-hidden');this.classList.toggle('ojt-collapsed')" style="cursor:pointer;user-select:none;display:inline-block;width:18px;color:#94A3B8;text-align:center;font-size:12px;flex-shrink:0">▼</span>`
    html += `<span class="ojt-bracket">{</span>`
    html += `<span class="ojt-block" id="${nodeId}">`
    keys.forEach((key, i) => {
      html += `<div class="ojt-line" style="padding-left:${indent + 20}px">`
      html += `<span class="ojt-key">"${escapeHtml(key)}"</span><span>: </span>`
      html += renderJsonValue(obj[key], depth + 1, `${path}.${key}`)
      if (i < keys.length - 1) html += `<span class="ojt-comma">,</span>`
      html += `</div>`
    })
    html += `</span>`
    html += `<span class="ojt-bracket">}</span>`
    return html
  }
  return escapeHtml(String(value))
}

function syntaxHighlightJson(json: string): string {
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^"\\])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = 'ojt-hl-num'
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'ojt-hl-key'
        } else {
          cls = 'ojt-hl-str'
        }
      } else if (/true|false/.test(match)) {
        cls = 'ojt-hl-bool'
      } else if (/null/.test(match)) {
        cls = 'ojt-hl-num'
      }
      return `<span class="${cls}">${match}</span>`
    },
  )
}

// ── Content block extraction ──────────────────────────────────────────────────

/**
 * Extracts a plain text string from a result value that may be:
 *   - A plain string (returned as-is)
 *   - A Claude/LangChain content blocks array: [{type:'text', text:'...'}, ...]
 *     (text blocks are concatenated with double newlines)
 * Returns null if no usable text could be extracted.
 */
function extractResultText(value: unknown): string | null {
  if (typeof value === 'string' && value.length > 0) return value
  if (Array.isArray(value)) {
    const parts: string[] = []
    for (const block of value) {
      if (
        block !== null &&
        typeof block === 'object' &&
        (block as Record<string, unknown>)['type'] === 'text' &&
        typeof (block as Record<string, unknown>)['text'] === 'string'
      ) {
        parts.push((block as Record<string, unknown>)['text'] as string)
      }
    }
    return parts.length > 0 ? parts.join('\n\n') : null
  }
  return null
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OutputTypeResultTab({
  outputType,
  outputData,
  outputSchema,
  dataTypeId,
  dataTypeSchema: externalSchema,
  validationStatus,
  rawOutput,
  dataTypeName,
}: OutputTypeResultTabProps) {
  const { t } = useTranslation()
  const [schemaOpen, setSchemaOpen] = useState(false)

  // Fetch schema if dataTypeId provided but no external schema
  const { data: fetchedSchema, isLoading: schemaLoading } = useDataType(
    dataTypeId && !externalSchema ? dataTypeId : '',
  )
  const effectiveSchema = externalSchema ?? fetchedSchema ?? null

  const badge = badgeForType(outputType, t, dataTypeName)

  // ── Markdown renderer ──
  const markdownHtml = useMemo(() => {
    if (outputType !== 'markdown' || !outputData) return ''
    const mdSource =
      extractResultText(outputData['markdown']) ??
      extractResultText(outputData['result']) ??
      JSON.stringify(outputData, null, 2)
    return simpleMarkdownToHtml(mdSource)
  }, [outputType, outputData])

  // ── Auto output text extraction (Claude content blocks or plain text) ──
  // When result is content blocks or a plain string, render that text instead of raw JSON tree.
  const autoExtractedText = useMemo(() => {
    if (outputType !== 'auto' || !outputData) return null
    return extractResultText(outputData['result']) ?? extractResultText(outputData['content']) ?? null
  }, [outputType, outputData])

  // ── Typed field values ──
  // For typed outputs with schema, extract field_values from outputData
  // or use outputData itself as the values map
  const fieldValues = useMemo<Record<string, unknown>>(() => {
    if (!outputData) return {}
    // Check if outputData has a nested field_values key (from AgentOutputResponse)
    if (typeof outputData['field_values'] === 'object' && outputData['field_values'] !== null) {
      return outputData['field_values'] as Record<string, unknown>
    }
    return outputData
  }, [outputData])

  // ── Typed JSON tree (fallback for typed without schema) ──
  const jsonTreeHtml = useMemo(() => {
    if (outputType !== 'typed') return ''
    // Only render JSON tree if we have no schema (typed but without data type)
    if (effectiveSchema) return ''
    jsonNodeCounter = 0
    return renderJsonValue(fieldValues, 0, 'root')
  }, [outputType, fieldValues, effectiveSchema])

  // ── Schema tree ──
  const schemaTreeHtml = useMemo(() => {
    if (!outputSchema) return ''
    jsonNodeCounter = 0
    return renderJsonValue(outputSchema, 0, 'schema')
  }, [outputSchema])

  // ── No data ──
  if (!outputData) {
    return (
      <Box sx={{ textAlign: 'center', py: 6, color: 'text.secondary' }}>
        <Typography variant="body2">
          {t('executions.resultTab.noData', { defaultValue: 'No result data available.' })}
        </Typography>
      </Box>
    )
  }

  // ── Loading schema ──
  if (schemaLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  // ── Show validation error ──
  const showValidationError = validationStatus === 'validation_error' || outputData?.['validation_status'] === 'validation_error'
  const effectiveRawOutput = rawOutput ?? (outputData?.['raw_output'] as string | undefined) ?? null
  const fieldErrors = outputData?.['validation_errors'] as Array<{ field: string; message: string }> | undefined

  return (
    <Box sx={{ py: 2 }}>
      {/* Meta row */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2, flexWrap: 'wrap' }}>
        <Typography
          variant="caption"
          sx={{ fontSize: 12, fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.4 }}
        >
          {t('agents.agentType.outputType', { defaultValue: 'Output Type' })}:
        </Typography>
        <Chip
          label={badge.label}
          size="small"
          sx={{
            fontWeight: 700,
            fontSize: 11,
            bgcolor: badge.bg,
            color: badge.color,
          }}
        />
        {outputType === 'typed' && outputSchema && !effectiveSchema && (
          <Chip
            label={t('executions.resultTab.validated', { defaultValue: 'Validated ✓' })}
            size="small"
            sx={{ fontSize: 11, bgcolor: '#F1F5F9', color: '#475569', fontWeight: 500 }}
          />
        )}
        {showValidationError && (
          <Chip
            label={t('executionLog.result.validationError', { defaultValue: 'Validation Error' })}
            size="small"
            sx={{ fontSize: 11, bgcolor: '#FEF2F2', color: '#DC2626', fontWeight: 600 }}
          />
        )}
      </Box>

      {/* ── Validation error banner ── */}
      {showValidationError && (
        <Box sx={{ mb: 2 }}>
          <Alert severity="error" variant="outlined">
            <Typography variant="body2" fontWeight={600}>
              {t('executionLog.result.validationErrorTitle', { defaultValue: 'Output Validation Failed' })}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {t('executionLog.result.validationErrorHint', {
                defaultValue: 'The agent output did not match the expected schema. Raw output is shown below as fallback.',
              })}
            </Typography>
            {fieldErrors && fieldErrors.length > 0 && (
              <Box component="ul" sx={{ mt: 1, mb: 0, pl: 2.5 }}>
                {fieldErrors.map((fe, i) => (
                  <Typography key={i} component="li" variant="caption" color="error">
                    <strong>{fe.field}</strong>: {fe.message}
                  </Typography>
                ))}
              </Box>
            )}
          </Alert>
        </Box>
      )}

      {/* ── Markdown Output ── */}
      {outputType === 'markdown' && (
        <MaximizableContent title={t('agents.agentType.outputMarkdown', { defaultValue: 'Markdown' })}>
          <Box
            className="result-markdown"
            sx={{
              '& h2': { fontSize: 20, fontWeight: 700, color: 'text.primary', mb: 1.5, pb: 1, borderBottom: 2, borderColor: 'divider' },
              '& h3': { fontSize: 16, fontWeight: 600, color: 'text.primary', mt: 2.5, mb: 1 },
              '& h4': { fontSize: 14, fontWeight: 600, color: 'text.primary', mt: 2, mb: 1 },
              '& p': { fontSize: 14, lineHeight: 1.65, mb: 1.25, color: 'text.primary' },
              '& strong': { fontWeight: 700 },
              '& ul, & ol': { pl: 3, mb: 1.5 },
              '& li': { fontSize: 14, lineHeight: 1.65, mb: 0.5 },
              '& code': { bgcolor: '#F1F5F9', px: 0.75, borderRadius: 0.5, fontSize: 13, fontFamily: 'monospace', color: '#C2410C' },
              '& pre': { bgcolor: '#1E293B', color: '#E2E8F0', p: 2, borderRadius: 1, overflowX: 'auto', fontSize: 13, lineHeight: 1.5, mb: 1.5, '& code': { bgcolor: 'transparent', color: 'inherit', p: 0, fontSize: 13 } },
              '& em': { fontStyle: 'italic', color: 'text.secondary' },
              '& blockquote': { borderLeft: 4, borderColor: 'primary.main', pl: 2, py: 1, my: 1.5, bgcolor: '#EFF6FF', borderRadius: '0 4px 4px 0', fontStyle: 'italic', color: 'text.secondary' },
              '& hr': { border: 'none', borderTop: 1, borderColor: 'divider', my: 2.5 },
            }}
            dangerouslySetInnerHTML={{ __html: markdownHtml }}
          />
        </MaximizableContent>
      )}

      {/* ── Typed Output (schema-based structured view) ── */}
      {outputType === 'typed' && effectiveSchema && (
        <Box>
          <Typography
            variant="caption"
            sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.4, mb: 1, display: 'block' }}
          >
            {t('executions.resultTab.structuredOutput', { defaultValue: 'Structured Output' })}
          </Typography>

          <MaximizableContent title={t('executions.resultTab.structuredOutput', { defaultValue: 'Structured Output' })}>
            <Box
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                overflow: 'hidden',
                bgcolor: 'background.paper',
              }}
            >
              <TypedOutputRenderer fields={effectiveSchema.fields} values={fieldValues} />
            </Box>
          </MaximizableContent>
        </Box>
      )}

      {/* ── Typed JSON Output (fallback when no schema) ── */}
      {outputType === 'typed' && !effectiveSchema && (
        <Box>
          <Typography
            variant="caption"
            sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.4, mb: 1, display: 'block' }}
          >
            {t('executions.resultTab.structuredOutput', { defaultValue: 'Structured Output' })}
          </Typography>

          <MaximizableContent title={t('executions.resultTab.structuredOutput', { defaultValue: 'Structured Output' })}>
            <Box
              sx={{
                fontFamily: 'monospace',
                fontSize: 13,
                lineHeight: 1.7,
                bgcolor: '#FAFBFC',
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 2,
                overflowX: 'auto',
                '& .ojt-line': { whiteSpace: 'nowrap', transition: 'background 0.2s', '&:hover': { bgcolor: 'rgba(0,0,0,0.02)' } },
                '& .ojt-key': { color: '#1D4ED8' },
                '& .ojt-str': { color: '#15803D' },
                '& .ojt-num': { color: '#C2410C' },
                '& .ojt-bool': { color: '#6D28D9' },
                '& .ojt-null': { color: '#9CA3AF', fontStyle: 'italic' },
                '& .ojt-bracket': { color: '#94A3B8' },
                '& .ojt-comma': { color: '#94A3B8' },
                '& .ojt-block': { display: 'inline' },
                '& .ojt-hidden': { display: 'none' },
                '& .ojt-toggle.ojt-collapsed': { transform: 'rotate(-90deg)' },
                '& .ojt-hl-key': { color: '#1D4ED8' },
                '& .ojt-hl-str': { color: '#15803D' },
                '& .ojt-hl-num': { color: '#C2410C' },
                '& .ojt-hl-bool': { color: '#6D28D9' },
              }}
              dangerouslySetInnerHTML={{ __html: jsonTreeHtml }}
            />
          </MaximizableContent>

          {/* Schema toggle */}
          {outputSchema && (
            <Box sx={{ mt: 2.5, pt: 1.5, borderTop: 1, borderColor: 'divider' }}>
              <Box
                component="button"
                onClick={() => setSchemaOpen(!schemaOpen)}
                sx={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 0.75,
                  px: 1.5,
                  py: 0.6,
                  border: 1,
                  borderColor: schemaOpen ? '#2563EB' : 'divider',
                  borderRadius: 20,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  bgcolor: schemaOpen ? '#DBEAFE' : 'background.paper',
                  color: schemaOpen ? '#2563EB' : 'text.secondary',
                  transition: 'all 0.2s ease',
                  '&:hover': { borderColor: '#2563EB', color: '#2563EB' },
                  fontFamily: 'inherit',
                }}
              >
                <Typography variant="caption" sx={{ fontSize: 10, transition: 'transform 0.2s', transform: schemaOpen ? 'rotate(180deg)' : undefined }}>
                  ▾
                </Typography>
                {schemaOpen
                  ? t('executions.resultTab.hideSchema', { defaultValue: 'Hide Output Schema' })
                  : t('executions.resultTab.showSchema', { defaultValue: 'Show Output Schema' })}
              </Box>
              <Collapse in={schemaOpen}>
                <Box
                  sx={{
                    mt: 1.5,
                    fontFamily: 'monospace',
                    fontSize: 13,
                    lineHeight: 1.7,
                    bgcolor: '#FAFBFC',
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    p: 2,
                    maxHeight: 400,
                    overflowY: 'auto',
                    '& .ojt-line': { whiteSpace: 'nowrap', transition: 'background 0.2s', '&:hover': { bgcolor: 'rgba(0,0,0,0.02)' } },
                    '& .ojt-key': { color: '#1D4ED8' },
                    '& .ojt-str': { color: '#15803D' },
                    '& .ojt-num': { color: '#C2410C' },
                    '& .ojt-bool': { color: '#6D28D9' },
                    '& .ojt-null': { color: '#9CA3AF', fontStyle: 'italic' },
                    '& .ojt-bracket': { color: '#94A3B8' },
                    '& .ojt-comma': { color: '#94A3B8' },
                    '& .ojt-block': { display: 'inline' },
                    '& .ojt-hidden': { display: 'none' },
                    '& .ojt-toggle.ojt-collapsed': { transform: 'rotate(-90deg)' },
                  }}
                  dangerouslySetInnerHTML={{ __html: schemaTreeHtml }}
                />
              </Collapse>
            </Box>
          )}
        </Box>
      )}

      {/* ── Auto Output ── */}
      {outputType === 'auto' && (
        <Box>
          <Typography
            variant="caption"
            sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.4, mb: 1, display: 'block' }}
          >
            {t('executions.resultTab.agentOutput', { defaultValue: 'Agent Output' })}
          </Typography>
          <MaximizableContent title={t('executions.resultTab.agentOutput', { defaultValue: 'Agent Output' })}>
            {autoExtractedText ? (
              // Use ContentRenderer for auto content-type-aware rendering
              <ContentRenderer mode="auto" content={autoExtractedText} />
            ) : (
              <Box
                component="pre"
                sx={{
                  bgcolor: '#FAFBFC',
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 1,
                  p: 2.5,
                  fontFamily: 'monospace',
                  fontSize: 13,
                  lineHeight: 1.6,
                  color: 'text.primary',
                  overflowX: 'auto',
                  whiteSpace: 'pre',
                  m: 0,
                  '& .ojt-hl-key': { color: '#1D4ED8' },
                  '& .ojt-hl-str': { color: '#15803D' },
                  '& .ojt-num': { color: '#C2410C' },
                  '& .ojt-bool': { color: '#6D28D9' },
                }}
                dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(JSON.stringify(outputData, null, 2)) }}
              />
            )}
          </MaximizableContent>
        </Box>
      )}

      {/* ── Raw output fallback for validation errors ── */}
      {showValidationError && effectiveRawOutput && (
        <Box sx={{ mt: 2.5, pt: 1.5, borderTop: 1, borderColor: 'divider' }}>
          <Typography
            variant="caption"
            sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.4, mb: 1, display: 'block' }}
          >
            {t('executionLog.result.rawFallback', { defaultValue: 'Raw Output (Fallback)' })}
          </Typography>
          <Box
            component="pre"
            sx={{
              bgcolor: '#FAFBFC',
              border: 1,
              borderColor: 'divider',
              borderRadius: 1,
              p: 2.5,
              fontFamily: 'monospace',
              fontSize: 12,
              lineHeight: 1.5,
              color: 'text.primary',
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
              m: 0,
              wordBreak: 'break-word',
            }}
          >
            {effectiveRawOutput}
          </Box>
        </Box>
      )}
    </Box>
  )
}
