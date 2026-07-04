import { useTranslation } from 'react-i18next'
import { Autocomplete, TextField } from '@mui/material'
import { MODULE_GROUPS } from '../../constants/resourceTypes'

const ALL_RESOURCE_TYPES = Object.values(MODULE_GROUPS).flatMap((g) => g.submodules)

const WILDCARD_OPTIONS = ['*::*', 'agent::*', 'integration::*', 'system::*']

interface FreeSoloResourceTypeSelectProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  error?: boolean
  helperText?: string
}

export default function FreeSoloResourceTypeSelect({
  value,
  onChange,
  disabled = false,
  error = false,
  helperText,
}: FreeSoloResourceTypeSelectProps) {
  const { t } = useTranslation()

  const allOptions = [...ALL_RESOURCE_TYPES, ...WILDCARD_OPTIONS]

  const isManifestValue = ALL_RESOURCE_TYPES.includes(value as typeof ALL_RESOURCE_TYPES[number])

  return (
    <Autocomplete
      freeSolo
      value={value}
      onChange={(_e, newValue) => {
        if (newValue !== null) {
          onChange(newValue)
        }
      }}
      onInputChange={(_e, newInputValue) => {
        onChange(newInputValue)
      }}
      options={allOptions}
      groupBy={(option) => {
        if (WILDCARD_OPTIONS.includes(option)) return t('permissions.roles.wildcardHint')
        const module = option.split('::')[0]
        const group = Object.values(MODULE_GROUPS).find((g) => g.submodules.includes(option as typeof g.submodules[number]))
        return group?.label ?? module
      }}
      disabled={disabled}
      renderInput={(params) => (
        <TextField
          {...params}
          size="small"
          label={t('permissions.roles.resourceType')}
          error={error}
          helperText={helperText}
        />
      )}
      renderOption={(props, option) => {
        const isWildcard = WILDCARD_OPTIONS.includes(option)
        return (
          <li {...props} key={option}>
            <span style={isWildcard ? { fontStyle: 'italic', color: 'grey.600' } : undefined}>
              {option}
            </span>
          </li>
        )
      }}
      sx={{
        '& .MuiAutocomplete-inputRoot': {
          fontStyle: isManifestValue ? undefined : 'italic',
        },
      }}
    />
  )
}
