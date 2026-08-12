import { Chip, Switch, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { DataTypeFieldType } from '../../types'

// ── Shared props ───────────────────────────────────────────────────────────────

interface FieldRendererProps {
  value: unknown
}

// ── BooleanFieldValue ──────────────────────────────────────────────────────────

export function BooleanFieldValue({ value }: FieldRendererProps) {
  const { t } = useTranslation()
  const isChecked = value === true || value === 'true' || value === 1

  if (value === null || value === undefined) {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.null', { defaultValue: 'null' })}
      </Typography>
    )
  }

  return (
    <Switch
      checked={isChecked}
      disabled
      size="small"
      sx={{ '& .MuiSwitch-track': { opacity: 0.5 } }}
    />
  )
}

// ── DateFieldValue ─────────────────────────────────────────────────────────────

export function DateFieldValue({ value }: FieldRendererProps) {
  const { t } = useTranslation()

  if (value === null || value === undefined) {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.null', { defaultValue: 'null' })}
      </Typography>
    )
  }

  if (value === '') {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.empty', { defaultValue: 'empty' })}
      </Typography>
    )
  }

  const dateStr = typeof value === 'string' ? value : String(value)
  const date = new Date(dateStr)

  if (Number.isNaN(date.getTime())) {
    return <Typography variant="body2">{dateStr}</Typography>
  }

  return (
    <Typography variant="body2">
      {date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })}
    </Typography>
  )
}

// ── EnumFieldValue ─────────────────────────────────────────────────────────────

export function EnumFieldValue({ value }: FieldRendererProps) {
  const { t } = useTranslation()

  if (value === null || value === undefined) {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.null', { defaultValue: 'null' })}
      </Typography>
    )
  }

  const label = typeof value === 'string' ? value : String(value)

  return <Chip label={label} size="small" variant="outlined" color="primary" />
}

// ── NumberFieldValue ───────────────────────────────────────────────────────────

export function NumberFieldValue({ value }: FieldRendererProps) {
  const { t } = useTranslation()

  if (value === null || value === undefined) {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.null', { defaultValue: 'null' })}
      </Typography>
    )
  }

  const num = typeof value === 'number' ? value : Number(value)

  if (Number.isNaN(num)) {
    return <Typography variant="body2">{String(value)}</Typography>
  }

  return (
    <Typography variant="body2">
      {num.toLocaleString(undefined, {
        maximumFractionDigits: 6,
        minimumFractionDigits: num % 1 !== 0 ? undefined : 0,
      })}
    </Typography>
  )
}

// ── StringFieldValue ───────────────────────────────────────────────────────────

export function StringFieldValue({ value }: FieldRendererProps) {
  const { t } = useTranslation()

  if (value === null || value === undefined) {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.null', { defaultValue: 'null' })}
      </Typography>
    )
  }

  const str = typeof value === 'string' ? value : String(value)

  if (str === '') {
    return (
      <Typography variant="body2" color="text.disabled" fontStyle="italic">
        {t('typedField.empty', { defaultValue: 'empty' })}
      </Typography>
    )
  }

  // Long strings get monospace styling
  if (str.length > 100) {
    return (
      <Typography
        variant="body2"
        sx={{
          fontFamily: 'monospace',
          fontSize: 12,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          maxHeight: 120,
          overflow: 'auto',
          bgcolor: '#FAFBFC',
          border: 1,
          borderColor: 'divider',
          borderRadius: 0.5,
          p: 1,
        }}
      >
        {str}
      </Typography>
    )
  }

  return <Typography variant="body2">{str}</Typography>
}

// ── Renderer dispatch ──────────────────────────────────────────────────────────

export function renderFieldValue(fieldType: DataTypeFieldType, value: unknown, key: string) {
  switch (fieldType) {
    case 'boolean':
      return <BooleanFieldValue key={key} value={value} />
    case 'date':
      return <DateFieldValue key={key} value={value} />
    case 'enum':
      return <EnumFieldValue key={key} value={value} />
    case 'number':
      return <NumberFieldValue key={key} value={value} />
    case 'string':
      return <StringFieldValue key={key} value={value} />
    default:
      return <StringFieldValue key={key} value={value} />
  }
}
