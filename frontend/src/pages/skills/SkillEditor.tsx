import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function SkillEditor() {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="h5">{t('skills.editSkill')}</Typography>
    </Box>
  )
}
