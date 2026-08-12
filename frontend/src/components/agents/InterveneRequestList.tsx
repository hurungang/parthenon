import { useState } from 'react'
import {
  Button,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver'
import { useTranslation } from 'react-i18next'
import type { InterveneRequest } from '../../types'
import { InterveneResponseDialog } from './InterveneResponseDialog'
interface InterveneRequestListProps {
  requests: InterveneRequest[]
  isLoading: boolean
  onSubmitResponse: (requestId: string, value: {
    approval_value?: boolean
    selected_choice?: string
    text_value?: string
  }) => Promise<void>
  onCancelRequest: (requestId: string) => Promise<void>
}

export function InterveneRequestList({
  requests,
  isLoading,
  onSubmitResponse,
}: InterveneRequestListProps) {
  const { t } = useTranslation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedRequest, setSelectedRequest] = useState<InterveneRequest | null>(null)

  const handleOpenDialog = (request: InterveneRequest) => {
    setSelectedRequest(request)
    setDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setSelectedRequest(null)
  }

  const handleSubmit = async (requestId: string, value: {
    approval_value?: boolean
    selected_choice?: string
    text_value?: string
  }) => {
    await onSubmitResponse(requestId, value)
  }

  const interventionTypeColor = (type: string) => {
    switch (type) {
      case 'approval':
        return 'warning'
      case 'choice':
        return 'info'
      case 'text':
        return 'secondary'
      default:
        return 'default'
    }
  }

  const interventionTypeLabel = (type: string) => {
    switch (type) {
      case 'approval':
        return t('intervene.typeApproval', 'Approval')
      case 'choice':
        return t('intervene.typeChoice', 'Choice')
      case 'text':
        return t('intervene.typeText', 'Text Input')
      default:
        return type
    }
  }

  if (isLoading) {
    return null
  }

  if (requests.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center' }}>
        <RecordVoiceOverIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
        <Typography color="text.secondary">
          {t('intervene.noPendingRequests', 'No pending intervention requests')}
        </Typography>
      </Paper>
    )
  }

  return (
    <>
      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('agents.sessions.sessionId')}</TableCell>
                <TableCell>{t('intervene.reason', 'Reason')}</TableCell>
                <TableCell>{t('intervene.type', 'Type')}</TableCell>
                <TableCell>{t('app.createdAt')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {requests.map((req) => (
                <TableRow key={req.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                      {req.agent_session_id.slice(0, 8)}…
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography
                      variant="body2"
                      sx={{
                        maxWidth: 300,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {req.reason}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={interventionTypeLabel(req.intervention_type)}
                      color={interventionTypeColor(req.intervention_type)}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {new Date(req.created_at).toLocaleString()}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => handleOpenDialog(req)}
                    >
                      {t('intervene.respond', 'Respond')}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
      <InterveneResponseDialog
        open={dialogOpen}
        request={selectedRequest}
        onClose={handleCloseDialog}
        onSubmit={handleSubmit}
      />
    </>
  )
}
