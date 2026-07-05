import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
} from '@mui/material'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import { useAgentData } from '../../hooks/useAgentData'
import { usePagination } from '../../hooks/usePagination'
import { AgentDataDetailDrawer } from './AgentDataDetailDrawer'
import type { AgentDataResponse } from '../../types'

export function AgentDataPage() {
  const { t } = useTranslation()
  const pag = usePagination()

  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState<string>('')

  const { data: agentTypes = [], isLoading: agentTypesLoading } = useAgentTypes()

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page: pag.page + 1,
      page_size: pag.rowsPerPage,
    }
    if (selectedAgentTypeId) params.agent_type_id = selectedAgentTypeId
    return params
  }, [selectedAgentTypeId, pag.page, pag.rowsPerPage])

  const {
    data: dataResponse,
    isLoading,
    error,
  } = useAgentData(queryParams)

  const [selectedRecord, setSelectedRecord] = useState<AgentDataResponse | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const items = dataResponse?.items ?? []
  const total = dataResponse?.total ?? 0

  const handleFilterChange = useCallback(
    (setter: (value: string) => void) =>
      (value: string) => {
        setter(value)
        pag.resetPage()
      },
    [pag],
  )

  const handleRowClick = (record: AgentDataResponse) => {
    setSelectedRecord(record)
    setDrawerOpen(true)
  }

  const handleCloseDrawer = () => {
    setDrawerOpen(false)
    setSelectedRecord(null)
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>
          {t('admin.agentData.title', { defaultValue: 'Agent Data' })}
        </Typography>
      </Box>

      {error && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} flexWrap="wrap" alignItems="flex-end">
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="agent-type-filter-label">
              {t('admin.agentData.filterAgentType', { defaultValue: 'Agent Type' })}
            </InputLabel>
            <Select
              labelId="agent-type-filter-label"
              value={selectedAgentTypeId}
              label={t('admin.agentData.filterAgentType', { defaultValue: 'Agent Type' })}
              onChange={(e) => handleFilterChange(setSelectedAgentTypeId)(e.target.value)}
              disabled={agentTypesLoading}
            >
              <MenuItem value="">
                <em>{t('admin.agentData.allAgentTypes', { defaultValue: 'All Agent Types' })}</em>
              </MenuItem>
              {agentTypes.map((at) => (
                <MenuItem key={at.id} value={at.id}>
                  {at.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Paper>

      {isLoading ? (
        <Box display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      ) : (
        <Box>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.agentData.columnTimestamp', { defaultValue: 'Timestamp' })}</TableCell>
                  <TableCell>{t('admin.agentData.columnDataName', { defaultValue: 'Data Name' })}</TableCell>
                  <TableCell>{t('admin.agentData.columnAgentType', { defaultValue: 'Agent Type' })}</TableCell>
                  <TableCell>{t('admin.agentData.columnSessionId', { defaultValue: 'Session ID' })}</TableCell>
                  <TableCell>{t('admin.agentData.columnDataType', { defaultValue: 'Data Type' })}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      {t('admin.agentData.noResults', { defaultValue: 'No agent data records found.' })}
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((record) => (
                    <TableRow
                      key={record.id}
                      hover
                      sx={{ cursor: 'pointer' }}
                      onClick={() => handleRowClick(record)}
                    >
                      <TableCell>
                        <Typography variant="body2">
                          {new Date(record.created_at).toLocaleString()}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontWeight={500}>
                          {record.data_name}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {record.agent_type_name ?? (record.agent_type_id?.slice(0, 8) ?? '—')}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                          {record.session_id?.slice(0, 12) ?? '—'}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {record.data_type}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={total}
            page={pag.page}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Box>
      )}

      <AgentDataDetailDrawer
        open={drawerOpen}
        record={selectedRecord}
        onClose={handleCloseDrawer}
      />
    </Box>
  )
}
