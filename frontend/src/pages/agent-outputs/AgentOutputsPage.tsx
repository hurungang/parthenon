import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Tabs,
  TextField,
  Typography,
  Chip,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDataTypes } from '../../hooks/useDataTypes'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import { useAgentOutputs, useAutoOutputs, useExportAgentOutputs } from '../../hooks/useAgentOutputs'
import { usePagination } from '../../hooks/usePagination'
import { renderFieldValue } from '../../components/executions/TypedFieldRenderers'
import { AgentOutputDetailDrawer } from './AgentOutputDetailDrawer'
import type {
  AgentOutputResponse,
  AgentOutputQueryParams,
} from '../../types'

/**
 * Agent Outputs admin page — filter, browse, and export typed agent outputs.
 *
 * Features:
 * - Filter bar: data type, agent type, date range
 * - Dynamic table columns based on selected data type schema
 * - Status badge (valid / validation_error)
 * - Row click opens detail drawer
 * - CSV export button
 */
export function AgentOutputsPage() {
  const { t } = useTranslation()
  const pag = usePagination()
  const autoPag = usePagination()

  // ── Tab state ─────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'typed' | 'auto'>('typed')

  // ── Filters ───────────────────────────────────────────────────────────────
  const [selectedDataTypeId, setSelectedDataTypeId] = useState<string>('')
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState<string>('')
  const [dateFrom, setDateFrom] = useState<string>('')
  const [dateTo, setDateTo] = useState<string>('')

  // Fetch data for filter dropdowns
  const { data: dataTypesResponse, isLoading: dataTypesLoading } = useDataTypes({
    page: 1,
    page_size: 100,
  })
  const { data: agentTypes = [], isLoading: agentTypesLoading } = useAgentTypes()

  // Selected data type for dynamic column generation
  const selectedDataType = useMemo(() => {
    if (!selectedDataTypeId || !dataTypesResponse?.items) return null
    return dataTypesResponse.items.find((dt) => dt.id === selectedDataTypeId) ?? null
  }, [selectedDataTypeId, dataTypesResponse?.items])

  // Build query params
  const queryParams: AgentOutputQueryParams = useMemo(() => {
    const params: AgentOutputQueryParams = {
      page: pag.page + 1,
      page_size: pag.rowsPerPage,
    }
    if (selectedDataTypeId) params.data_type_id = selectedDataTypeId
    if (selectedAgentTypeId) params.agent_type_id = selectedAgentTypeId
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    return params
  }, [selectedDataTypeId, selectedAgentTypeId, dateFrom, dateTo, pag.page, pag.rowsPerPage])

  const {
    data: outputsResponse,
    isLoading,
    error,
  } = useAgentOutputs(queryParams)

  // ── Auto outputs query ────────────────────────────────────────────────────
  const autoQueryParams = useMemo(() => ({
    agent_type_id: selectedAgentTypeId || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    page: autoPag.page + 1,
    page_size: autoPag.rowsPerPage,
  }), [selectedAgentTypeId, dateFrom, dateTo, autoPag.page, autoPag.rowsPerPage])

  const {
    data: autoOutputsResponse,
    isLoading: autoLoading,
    error: autoError,
  } = useAutoOutputs(autoQueryParams)

  const exportMutation = useExportAgentOutputs()

  const [selectedOutput, setSelectedOutput] = useState<AgentOutputResponse | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const items = outputsResponse?.items ?? []
  const total = outputsResponse?.total ?? 0

  // Reset pagination to page 0 when filters change
  const handleFilterChange = useCallback(
    (setter: (value: string) => void) =>
      (value: string) => {
        setter(value)
        pag.resetPage()
      },
    [pag],
  )

  // ── Dynamic columns ─────────────────────────────────────────────────────
  const dynamicFields = selectedDataType?.fields ?? []

  const handleRowClick = (output: AgentOutputResponse) => {
    setSelectedOutput(output)
    setDrawerOpen(true)
  }

  const handleCloseDrawer = () => {
    setDrawerOpen(false)
    setSelectedOutput(null)
  }

  const handleExportCsv = () => {
    void exportMutation.mutateAsync({
      data_type_id: selectedDataTypeId || undefined,
      agent_type_id: selectedAgentTypeId || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    })
  }

  return (
    <Box>
      {/* Page header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>
          {t('admin.agentOutputs.title')}
        </Typography>
        {activeTab === 'typed' && (
          <Button
            variant="contained"
            startIcon={<DownloadIcon />}
            onClick={handleExportCsv}
            disabled={exportMutation.isPending}
          >
            {exportMutation.isPending
              ? t('app.saving', { defaultValue: 'Exporting…' })
              : t('admin.agentOutputs.exportCsv')}
          </Button>
        )}
      </Box>

      {/* Error state */}
      {(error || autoError) && (
        <PermissionDeniedAlert error={error ?? autoError} fallbackMessage={t('app.error')} />
      )}

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onChange={(_, v) => { setActiveTab(v as 'typed' | 'auto'); pag.resetPage(); autoPag.resetPage() }}
        sx={{ mb: 2 }}
      >
        <Tab value="typed" label={t('admin.agentOutputs.tabTyped', { defaultValue: 'Typed Outputs' })} />
        <Tab value="auto" label={t('admin.agentOutputs.tabAuto', { defaultValue: 'Auto Outputs' })} />
      </Tabs>

      {/* Filter bar */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} flexWrap="wrap" alignItems="flex-end">
          {/* Data type selector — only for typed tab */}
          {activeTab === 'typed' && (
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel id="data-type-filter-label">
                {t('admin.agentOutputs.filterDataType')}
              </InputLabel>
              <Select
                labelId="data-type-filter-label"
                value={selectedDataTypeId}
                label={t('admin.agentOutputs.filterDataType')}
                onChange={(e) => handleFilterChange(setSelectedDataTypeId)(e.target.value)}
                disabled={dataTypesLoading}
              >
                <MenuItem value="">
                  <em>{t('admin.agentOutputs.allDataTypes', { defaultValue: 'All Data Types' })}</em>
                </MenuItem>
                {(dataTypesResponse?.items ?? []).map((dt) => (
                  <MenuItem key={dt.id} value={dt.id}>
                    {dt.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="agent-type-filter-label">
              {t('admin.agentOutputs.filterAgentType')}
            </InputLabel>
            <Select
              labelId="agent-type-filter-label"
              value={selectedAgentTypeId}
              label={t('admin.agentOutputs.filterAgentType')}
              onChange={(e) => handleFilterChange(setSelectedAgentTypeId)(e.target.value)}
              disabled={agentTypesLoading}
            >
              <MenuItem value="">
                <em>{t('admin.agentOutputs.allAgentTypes', { defaultValue: 'All Agent Types' })}</em>
              </MenuItem>
              {agentTypes.map((at) => (
                <MenuItem key={at.id} value={at.id}>
                  {at.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* Date from */}
          <TextField
            size="small"
            type="date"
            label={t('admin.agentOutputs.filterDateFrom', { defaultValue: 'From' })}
            value={dateFrom}
            onChange={(e) => handleFilterChange(setDateFrom)(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 180 }}
          />

          {/* Date to */}
          <TextField
            size="small"
            type="date"
            label={t('admin.agentOutputs.filterDateTo', { defaultValue: 'To' })}
            value={dateTo}
            onChange={(e) => handleFilterChange(setDateTo)(e.target.value)}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 180 }}
          />
        </Box>
      </Paper>

      {/* Loading state */}
      {(activeTab === 'typed' ? isLoading : autoLoading) ? (
        <Box display="flex" justifyContent="center" py={4}>
          <CircularProgress />
        </Box>
      ) : activeTab === 'typed' ? (
        <Box>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.agentOutputs.columnTimestamp')}</TableCell>
                  <TableCell>{t('admin.agentOutputs.columnAgentType')}</TableCell>
                  <TableCell>{t('admin.agentOutputs.columnDataType')}</TableCell>
                  {dynamicFields.map((field) => (
                    <TableCell key={field.name}>
                      {field.name}
                    </TableCell>
                  ))}
                  <TableCell>{t('admin.agentOutputs.columnStatus')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4 + dynamicFields.length} align="center">
                      {t('admin.agentOutputs.noResults')}
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((output) => {
                    const statusValid = output.validation_status === 'valid'
                    return (
                      <TableRow
                        key={output.id}
                        hover
                        sx={{ cursor: 'pointer' }}
                        onClick={() => handleRowClick(output)}
                      >
                        <TableCell>
                          <Typography variant="body2">
                            {new Date(output.created_at).toLocaleString()}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {output.agent_type_name ?? output.agent_type_id.slice(0, 8)}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {output.data_type_name ?? output.data_type_id.slice(0, 8)}
                          </Typography>
                        </TableCell>
                        {dynamicFields.map((field) => (
                          <TableCell key={field.name}>
                            {renderFieldValue(
                              field.type,
                              output.field_values?.[field.name] ?? null,
                              `cell-${output.id}-${field.name}`,
                            )}
                          </TableCell>
                        ))}
                        <TableCell>
                          <Chip
                            icon={statusValid ? <CheckCircleIcon /> : <ErrorIcon />}
                            label={
                              statusValid
                                ? t('admin.agentOutputs.statusValid')
                                : t('admin.agentOutputs.statusError')
                            }
                            color={statusValid ? 'success' : 'error'}
                            size="small"
                            variant="outlined"
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })
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
      ) : (
        /* ── Auto Outputs Tab ─────────────────────────────────────────────── */
        <Box>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.agentOutputs.columnTimestamp')}</TableCell>
                  <TableCell>{t('admin.agentOutputs.columnAgentType')}</TableCell>
                  <TableCell>{t('admin.agentOutputs.columnPreview', { defaultValue: 'Result Preview' })}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(autoOutputsResponse?.items ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} align="center">
                      {t('admin.agentOutputs.noResults')}
                    </TableCell>
                  </TableRow>
                ) : (
                  (autoOutputsResponse?.items ?? []).map((item) => (
                    <TableRow key={item.session_id} hover>
                      <TableCell>
                        <Typography variant="body2">
                          {new Date(item.created_at).toLocaleString()}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {item.agent_type_name ?? item.agent_type_id.slice(0, 8)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{
                            maxWidth: 480,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            color: item.output_preview ? 'text.primary' : 'text.disabled',
                          }}
                          title={item.output_preview ?? ''}
                        >
                          {item.output_preview ?? t('admin.agentOutputs.noPreview', { defaultValue: '—' })}
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
            count={autoOutputsResponse?.total ?? 0}
            page={autoPag.page}
            onPageChange={autoPag.onPageChange}
            rowsPerPage={autoPag.rowsPerPage}
            onRowsPerPageChange={autoPag.onRowsPerPageChange}
            rowsPerPageOptions={autoPag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Box>
      )}

      {/* Detail Drawer */}
      <AgentOutputDetailDrawer
        open={drawerOpen}
        output={selectedOutput}
        dataType={selectedDataType}
        onClose={handleCloseDrawer}
      />
    </Box>
  )
}
