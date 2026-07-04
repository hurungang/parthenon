import { useTranslation } from 'react-i18next'
import { Autocomplete, Chip, TextField } from '@mui/material'

const STANDARD_ACTIONS = [
  'create', 'read', 'update', 'delete', 'execute',
  'manage', 'approve', 'reject', 'view', 'respond',
]

interface FreeSoloActionSelectProps {
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
  error?: boolean
  helperText?: string
}

export default function FreeSoloActionSelect({
  value,
  onChange,
  disabled = false,
  error = false,
  helperText,
}: FreeSoloActionSelectProps) {
  const { t } = useTranslation()

  return (
    <Autocomplete
      multiple
      freeSolo
      value={value}
      onChange={(_e, newValue) => {
        onChange(newValue.filter((v): v is string => typeof v === 'string'))
      }}
      options={STANDARD_ACTIONS}
      disabled={disabled}
      renderTags={(tagValue, getTagProps) =>
        tagValue.map((option, index) => {
          const isStandard = STANDARD_ACTIONS.includes(option)
          const { key, ...chipProps } = getTagProps({ index })
          return (
            <Chip
              key={key}
              label={option}
              size="small"
              variant={isStandard ? 'filled' : 'outlined'}
              sx={isStandard ? undefined : { fontStyle: 'italic', borderStyle: 'dashed' }}
              {...chipProps}
            />
          )
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={t('permissions.roles.actions')}
          error={error}
          helperText={helperText}
          placeholder={disabled ? t('permissions.roles.selectResourceTypeFirst') : t('permissions.roles.selectActions')}
        />
      )}
    />
  )
}
