import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, Button, IconButton, Stack, TextField, Typography } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import type { EnumValue } from '../../types'

/** Editable enum value row: value + optional description. */
interface EnumValueRow {
  value: string
  description: string
}

function enumValuesToRows(values: EnumValue[] | null | undefined): EnumValueRow[] {
  if (!values || values.length === 0) return []
  return values.map((v) =>
    typeof v === 'string'
      ? { value: v, description: '' }
      : { value: v.value, description: v.description ?? '' },
  )
}

function rowsToEnumValues(rows: EnumValueRow[]): EnumValue[] {
  return rows
    .filter((r) => r.value.trim())
    .map((r) =>
      r.description.trim()
        ? { value: r.value.trim(), description: r.description.trim() }
        : r.value.trim(),
    )
}

function sameCommittedRows(a: EnumValueRow[], b: EnumValueRow[]): boolean {
  return JSON.stringify(rowsToEnumValues(a)) === JSON.stringify(rowsToEnumValues(b))
}

interface EnumValuesEditorProps {
  /** Enum values from the parent field (legacy strings or {value, description} objects). */
  values: EnumValue[] | null | undefined
  /** Invoked with the committed (non-empty) values, or null when nothing is committed. */
  onChange: (values: EnumValue[] | null) => void
}

/**
 * Editor for the enum values of a data type field. Renders as an indented
 * sub-block nested under the field row.
 *
 * Owns the row state locally so that empty, not-yet-committed rows (e.g. right
 * after "Add Value") stay visible; only rows with a non-empty value are pushed
 * to the parent via onChange.
 */
export function EnumValuesEditor({ values, onChange }: EnumValuesEditorProps) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<EnumValueRow[]>(() => enumValuesToRows(values))

  // Sync from the parent when external values change, but never clobber local
  // rows whose committed form matches (preserves in-progress empty rows).
  useEffect(() => {
    setRows((prev) => {
      const incoming = enumValuesToRows(values)
      return sameCommittedRows(prev, incoming) ? prev : incoming
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values])

  const updateRow = (index: number, patch: Partial<EnumValueRow>) => {
    setRows((prev) => {
      const next = prev.map((r, i) => (i === index ? { ...r, ...patch } : r))
      onChange(next.length > 0 ? rowsToEnumValues(next) : null)
      return next
    })
  }

  const handleAdd = () => {
    setRows((prev) => [...prev, { value: '', description: '' }])
  }

  const handleRemove = (index: number) => {
    setRows((prev) => {
      const next = prev.filter((_, i) => i !== index)
      onChange(next.length > 0 ? rowsToEnumValues(next) : null)
      return next
    })
  }

  return (
    <Box
      sx={{
        width: '100%',
        mt: 1,
        ml: 2,
        pl: 2,
        py: 1,
        borderLeft: 2,
        borderColor: 'divider',
        bgcolor: 'action.hover',
        borderRadius: 1,
      }}
    >
      <Typography variant="caption" color="text.secondary" display="block">
        {t('admin.dataTypes.enumValues')}
      </Typography>
      <Typography variant="caption" color="text.secondary" display="block">
        {t('admin.dataTypes.enumValuesHint')}
      </Typography>

      {rows.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {t('admin.dataTypes.enumValuesRequired')}
        </Typography>
      )}

      {rows.map((row, vIdx) => (
        <Stack
          key={vIdx}
          direction="row"
          spacing={1}
          alignItems="center"
          sx={{ mt: 0.5 }}
          data-testid={`enum-value-row-${vIdx}`}
        >
          <TextField
            label={t('admin.dataTypes.enumValue')}
            value={row.value}
            size="small"
            sx={{ minWidth: 120, flex: 1 }}
            placeholder="value"
            onChange={(e) => updateRow(vIdx, { value: e.target.value })}
          />
          <TextField
            label={t('admin.dataTypes.enumValueDescription')}
            value={row.description}
            size="small"
            sx={{ minWidth: 180, flex: 2 }}
            placeholder={t('admin.dataTypes.enumValueDescriptionHint')}
            onChange={(e) => updateRow(vIdx, { description: e.target.value })}
          />
          <IconButton
            size="small"
            aria-label={t('admin.dataTypes.removeEnumValue')}
            onClick={() => handleRemove(vIdx)}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Stack>
      ))}

      <Button size="small" startIcon={<AddIcon />} sx={{ mt: 0.5 }} onClick={handleAdd}>
        {t('admin.dataTypes.addEnumValue')}
      </Button>
    </Box>
  )
}
