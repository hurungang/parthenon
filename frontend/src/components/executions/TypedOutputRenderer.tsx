import { Box, Divider, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { renderFieldValue } from './TypedFieldRenderers'
import type { AgentDataTypeField } from '../../types'

// ── Props ─────────────────────────────────────────────────────────────────────

interface TypedOutputRendererProps {
  fields: AgentDataTypeField[]
  values: Record<string, unknown>
}

// ── Component ──────────────────────────────────────────────────────────────────

/**
 * Renders typed output as a structured field-by-field view.
 * Each field definition from the data type schema is rendered as a labelled row,
 * with the value displayed using the appropriate type-aware sub-component.
 */
export function TypedOutputRenderer({ fields, values }: TypedOutputRendererProps) {
  const { t } = useTranslation()

  if (!fields || fields.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" fontStyle="italic">
        {t('typedField.empty', { defaultValue: 'No fields defined.' })}
      </Typography>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {fields.map((field, index) => {
        const rawValue = values[field.name] ?? field.default ?? null
        const isMissing = rawValue === null && field.required

        return (
          <Box key={field.name}>
            {index > 0 && <Divider />}
            <Box
              sx={{
                display: 'flex',
                alignItems: 'flex-start',
                py: 1.5,
                px: 1,
                gap: 2,
                '&:hover': { bgcolor: 'action.hover' },
              }}
            >
              {/* Field label */}
              <Box sx={{ flex: '0 0 200px', minWidth: 140 }}>
                <Typography
                  variant="body2"
                  fontWeight={600}
                  color={isMissing ? 'error' : 'text.primary'}
                  sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}
                >
                  {field.name}
                  {field.required && (
                    <Typography component="span" variant="caption" color="error" sx={{ lineHeight: 1 }}>
                      *
                    </Typography>
                  )}
                </Typography>
                {field.type && (
                  <Typography variant="caption" color="text.disabled" sx={{ textTransform: 'uppercase', fontSize: 10, letterSpacing: 0.3 }}>
                    {field.type}
                  </Typography>
                )}
              </Box>

              {/* Field value */}
              <Box sx={{ flex: 1, minWidth: 0 }}>
                {isMissing ? (
                  <Typography variant="body2" color="error" fontStyle="italic">
                    {t('typedField.missing', { defaultValue: 'Missing required value' })}
                  </Typography>
                ) : (
                  renderFieldValue(field.type, rawValue, `field-${field.name}`)
                )}
              </Box>
            </Box>
          </Box>
        )
      })}
    </Box>
  )
}
