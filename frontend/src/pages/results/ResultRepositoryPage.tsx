import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { usePagination } from '../../hooks/usePagination'
import {
  Box,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
  IconButton,
  Chip,
  Tab,
  Tabs,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { DecisionResultView } from '../../components/results/DecisionResultView'
import { getDecisionResults } from '../../api/systemOneApi'
import type { DecisionExecutionResult } from '../../api/systemOneApi'
import type { ResultRecord } from '../../types'

/**
 * Result repository page — result record list with detail panel,
 * plus a decision-execution results tab.
 */
export function ResultRepositoryPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'results' | 'decision'>('results')
  const [selected, setSelected] = useState<ResultRecord | null>(null)
  const [selectedDecision, setSelectedDecision] =
    useState<DecisionExecutionResult | null>(null)
  const pag = usePagination()

  const { data: results, isLoading, error } = useQuery<ResultRecord[]>({
    queryKey: ['results', { page: pag.page, rowsPerPage: pag.rowsPerPage }],
    queryFn: async () => {
      const { data } = await apiClient.get<ResultRecord[]>('/results', {
        params: { limit: pag.limit, offset: pag.offset },
      })
      return data
    },
  })

  const {
    data: decisionResults,
    isLoading: decisionLoading,
    error: decisionError,
  } = useQuery<DecisionExecutionResult[]>({
    queryKey: ['results', 'decision'],
    queryFn: () => getDecisionResults({ limit: 50 }),
    enabled: tab === 'decision',
  })

  const selectedContent = typeof selected?.payload?.content === 'string'
    ? selected.payload.content
    : null

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>{t('results.title')}</Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="results" label={t('results.tabResults')} />
        <Tab value="decision" label={t('results.tabDecision')} />
      </Tabs>

      {tab === 'decision' ? (
        <Box>
          {decisionError && (
            <PermissionDeniedAlert error={decisionError} fallbackMessage={t('app.error')} />
          )}
          {decisionLoading ? (
            <CircularProgress />
          ) : (
            <TableContainer component={Paper}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>{t('results.decision.tool')}</TableCell>
                    <TableCell>{t('results.decision.outcome')}</TableCell>
                    <TableCell>{t('app.status')}</TableCell>
                    <TableCell>{t('app.createdAt')}</TableCell>
                    <TableCell>{t('app.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(decisionResults ?? []).map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          {r.decision_tool_id}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={t(`results.decision.outcomes.${r.outcome}`)}
                          size="small"
                          color={
                            r.outcome === 'act'
                              ? 'success'
                              : r.outcome === 'confirm'
                                ? 'warning'
                                : 'error'
                          }
                        />
                      </TableCell>
                      <TableCell>
                        {r.status === 'failed'
                          ? t('results.decision.failed')
                          : t('results.decision.completed')}
                      </TableCell>
                      <TableCell>{new Date(r.created_at).toLocaleString()}</TableCell>
                      <TableCell>
                        <IconButton
                          size="small"
                          onClick={() => setSelectedDecision(r)}
                        >
                          <OpenInNewIcon />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                  {(decisionResults ?? []).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} align="center">{t('app.noData')}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      ) : (
        <Box>
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress />
      ) : (
        <Box>
          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Title</TableCell>
                  <TableCell>{t('results.contentType')}</TableCell>
                  <TableCell>{t('results.tags')}</TableCell>
                  <TableCell>{t('app.createdAt')}</TableCell>
                  <TableCell>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(results ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.title ?? '—'}</TableCell>
                    <TableCell><code>{r.content_type}</code></TableCell>
                    <TableCell>
                      {(r.tags ?? []).map((tag) => (
                        <Chip key={tag} label={tag} size="small" sx={{ mr: 0.5 }} />
                      ))}
                    </TableCell>
                    <TableCell>{new Date(r.created_at).toLocaleString()}</TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => setSelected(r)}>
                        <OpenInNewIcon />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
                {(results ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">{t('app.noData')}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={-1}
            page={pag.page}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Box>
      )}
        </Box>
      )}

      {/* Decision result detail dialog */}
      <Dialog
        open={!!selectedDecision}
        onClose={() => setSelectedDecision(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {t('results.decision.detailTitle', {
            tool: selectedDecision?.decision_tool_id ?? '',
          })}
        </DialogTitle>
        <DialogContent dividers>
          {selectedDecision && <DecisionResultView result={selectedDecision} />}
        </DialogContent>
      </Dialog>

      {/* Detail dialog */}
      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        <DialogTitle>{selected?.title ?? 'Result Detail'}</DialogTitle>
        <DialogContent>
          {selected?.content_type === 'text/markdown' && selectedContent ? (
            <Box sx={{ '& p': { my: 1 }, '& pre': { overflow: 'auto' }, '& code': { fontFamily: 'monospace' } }}>
              <ReactMarkdown>{selectedContent}</ReactMarkdown>
            </Box>
          ) : selected?.content_type === 'text/plain' && selectedContent ? (
            <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13 }}>
              {selectedContent}
            </Typography>
          ) : (
            <Box component="pre" sx={{ overflow: 'auto', fontSize: 12 }}>
              {JSON.stringify(selected?.payload, null, 2)}
            </Box>
          )}
        </DialogContent>
      </Dialog>
    </Box>
  )
}
