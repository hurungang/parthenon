import Cron from 'react-js-cron'
import 'react-js-cron/dist/styles.css'
import { useTranslation } from 'react-i18next'
import { TextField, Typography, Box } from '@mui/material'
import { toString } from 'cronstrue'

interface CronEditorProps {
  value: string
  onChange: (cron: string) => void
}

export default function CronEditor({ value, onChange }: CronEditorProps) {
  const { t } = useTranslation()
  let cronDesc = ''
  try {
    cronDesc = toString(value, { throwExceptionOnParseError: true })
  } catch {
    cronDesc = t('schedules.invalidCron')
  }

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <style>{`.ant-select-dropdown,.ant-picker-dropdown{z-index:1500!important}`}</style>
      <TextField
        label={t('schedules.cronExpression')}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        size="small"
        fullWidth
        placeholder="* * * * *"
      />
      <Typography variant="caption" color="text.secondary">
        {cronDesc}
      </Typography>
      <Cron
        value={value}
        setValue={onChange}
        shortcuts={[
          '@daily',
          '@hourly',
          '@weekly',
          '@monthly',
          '@yearly',
        ]}
        humanizeLabels
        humanizeValue
        locale={{
          everyText: t('schedules.every'),
        }}
        getPopupContainer={() => document.body}
      />
    </Box>
  )
}
