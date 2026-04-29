import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  TableRow,
  Typography,
  IconButton,
  Chip,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import type { ResultRecord } from '../../types'

/**
 * Result repository page — result record list with detail panel.
 */
export function ResultRepositoryPage() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<ResultRecord | null>(null)

  const { data: results, isLoading } = useQuery<ResultRecord[]>({
    queryKey: ['results'],
    queryFn: async () => {
      const { data } = await apiClient.get<ResultRecord[]>('/results')
      return data
    },
  })

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>{t('results.title')}</Typography>

      {isLoading ? (
        <CircularProgress />
      ) : (
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
      )}

      {/* Detail dialog */}
      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        <DialogTitle>{selected?.title ?? 'Result Detail'}</DialogTitle>
        <DialogContent>
          <pre style={{ overflow: 'auto', fontSize: 12 }}>
            {JSON.stringify(selected?.payload, null, 2)}
          </pre>
        </DialogContent>
      </Dialog>
    </Box>
  )
}
