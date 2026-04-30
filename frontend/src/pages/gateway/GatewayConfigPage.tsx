import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentType } from '../../types'

/**
 * Gateway configuration page — gateway routes per agent type with copyable endpoint URLs.
 */
export function GatewayConfigPage() {
  const { t } = useTranslation()
  const { data: agentTypes, isLoading, error } = useAgentTypes()

  const handleCopy = (text: string) => {
    void navigator.clipboard.writeText(text)
  }

  const baseUrl = `${window.location.protocol}//${window.location.host}`

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {t('gateway.title')}
      </Typography>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('gateway.agentType')}</TableCell>
                <TableCell>{t('agents.mode')}</TableCell>
                <TableCell>{t('gateway.httpEndpoint')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(agentTypes ?? []).map((at: AgentType) => {
                const initUrl = `${baseUrl}/gateway/${at.id}/init`
                return (
                  <TableRow key={at.id}>
                    <TableCell>{at.name}</TableCell>
                    <TableCell>{at.mode}</TableCell>
                    <TableCell>
                      <code style={{ fontSize: 12 }}>{initUrl}</code>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={t('gateway.copyEndpoint')}>
                        <Button
                          size="small"
                          startIcon={<ContentCopyIcon />}
                          onClick={() => handleCopy(initUrl)}
                        >
                          {t('app.copy')}
                        </Button>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                )
              })}
              {(agentTypes ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
