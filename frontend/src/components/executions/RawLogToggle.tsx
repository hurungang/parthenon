import { useState } from 'react'
import { Box, FormControlLabel, IconButton, Switch, Tooltip, Typography } from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import { useTranslation } from 'react-i18next'

interface Props {
  checked: boolean
  onChange: (checked: boolean) => void
  rawLogText: string
}

export function RawLogToggle({ checked, onChange, rawLogText }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    void navigator.clipboard.writeText(rawLogText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <Box display="flex" alignItems="center" gap={1}>
      <Typography variant="caption" color={checked ? 'text.secondary' : 'text.primary'}>
        {t('agents.sessions.logViewer.rawToggle.friendly')}
      </Typography>
      <FormControlLabel
        control={
          <Switch
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            size="small"
            inputProps={{ 'aria-label': t('agents.sessions.logViewer.rawToggle.ariaLabel') }}
          />
        }
        label={
          <Typography variant="caption" color={checked ? 'text.primary' : 'text.secondary'}>
            {t('agents.sessions.logViewer.rawToggle.raw')}
          </Typography>
        }
        sx={{ m: 0 }}
      />
      {checked && (
        <Tooltip
          title={
            copied
              ? t('agents.sessions.logViewer.rawToggle.copied')
              : t('agents.sessions.logViewer.rawToggle.copyToClipboard')
          }
        >
          <IconButton size="small" onClick={handleCopy} aria-label={t('agents.sessions.logViewer.rawToggle.copyToClipboard')}>
            {copied ? <CheckIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      )}
    </Box>
  )
}
