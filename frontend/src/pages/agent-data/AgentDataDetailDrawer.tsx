import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
  TableContainer,
  Paper,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { AgentDataResponse } from '../../types'

interface Props {
  open: boolean
  record: AgentDataResponse | null
  onClose: () => void
}

export function AgentDataDetailDrawer({ open, record, onClose }: Props) {
  const { t } = useTranslation()

  if (!record) return null

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        {t('admin.agentData.detailTitle', { defaultValue: 'Agent Data Detail' })}
      </DialogTitle>
      <DialogContent dividers>
        <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
          <Table size="small">
            <TableBody>
              <TableRow>
                <TableCell sx={{ fontWeight: 600, width: 140 }}>
                  {t('admin.agentData.columnTimestamp', { defaultValue: 'Timestamp' })}
                </TableCell>
                <TableCell>{new Date(record.created_at).toLocaleString()}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>
                  {t('admin.agentData.columnDataName', { defaultValue: 'Data Name' })}
                </TableCell>
                <TableCell>{record.data_name}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>
                  {t('admin.agentData.columnAgentType', { defaultValue: 'Agent Type' })}
                </TableCell>
                <TableCell>
                  {record.agent_type_name ?? (record.agent_type_id?.slice(0, 8) ?? '—')}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>
                  {t('admin.agentData.columnSessionId', { defaultValue: 'Session ID' })}
                </TableCell>
                <TableCell>{record.session_id ?? '—'}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>
                  {t('admin.agentData.columnDataType', { defaultValue: 'Data Type' })}
                </TableCell>
                <TableCell>{record.data_type}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>

        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          {t('admin.agentData.dataValueLabel', { defaultValue: 'Data Value' })}
        </Typography>
        <Box
          component="pre"
          sx={{
            p: 2,
            bgcolor: 'grey.100',
            borderRadius: 1,
            overflow: 'auto',
            maxHeight: 400,
            fontSize: '0.85rem',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {JSON.stringify(record.data_value, null, 2)}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>
          {t('app.close', { defaultValue: 'Close' })}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
