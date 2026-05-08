import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useAllTools, useMcpServers, useToolSkills } from '../../hooks/useMcpServers'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { TestMcpToolDialog } from './TestMcpToolDialog'
import type { McpTool } from '../../types'

function SkillChips({ toolId }: { toolId: string }) {
  const { data: skills } = useToolSkills(toolId)
  if (!skills?.length) return null
  return (
    <Stack direction="row" spacing={0.5} flexWrap="wrap">
      {skills.map((s) => (
        <Chip key={s.id} label={s.name} size="small" variant="outlined" color="primary" />
      ))}
    </Stack>
  )
}

export function McpToolBrowser() {
  const { t } = useTranslation()
  const { data: tools, isLoading, error } = useAllTools()
  const { data: servers } = useMcpServers()
  const [search, setSearch] = useState('')
  const [serverFilter, setServerFilter] = useState('')
  const [testingTool, setTestingTool] = useState<McpTool | null>(null)

  const serverMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const s of servers ?? []) m[s.id] = s.slug
    return m
  }, [servers])

  // Group tools by server slug
  const grouped = useMemo(() => {
    const filtered = (tools ?? []).filter((tool: McpTool) => {
      const matchSearch = !search || tool.name.toLowerCase().includes(search.toLowerCase()) ||
        (tool.description ?? '').toLowerCase().includes(search.toLowerCase())
      const matchServer = !serverFilter || tool.server_id === serverFilter
      return matchSearch && matchServer
    })
    const groups: Record<string, McpTool[]> = {}
    for (const tool of filtered) {
      const slug = serverMap[tool.server_id] ?? tool.server_id
      if (!groups[slug]) groups[slug] = []
      groups[slug].push(tool)
    }
    return groups
  }, [tools, search, serverFilter, serverMap])

  return (
    <Box>
      <Stack direction="row" spacing={2} mb={2} alignItems="center">
        <TextField
          placeholder={t('app.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          sx={{ width: 280 }}
        />
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>{t('mcp.tabs.serverFilter')}</InputLabel>
          <Select
            value={serverFilter}
            label={t('mcp.tabs.serverFilter')}
            onChange={(e) => setServerFilter(e.target.value)}
          >
            <MenuItem value="">{t('mcp.tabs.allServers')}</MenuItem>
            {(servers ?? []).map((s) => (
              <MenuItem key={s.id} value={s.id}>{s.slug}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress />
      ) : (
        Object.entries(grouped).map(([slug, groupTools]) => (
          <Box key={slug} mb={3}>
            <Typography variant="subtitle1" fontWeight={600} color="primary" mb={1}>
              <code>{slug}</code>
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('app.name')}</TableCell>
                    <TableCell>{t('app.description')}</TableCell>
                    <TableCell>{t('skills.title')}</TableCell>
                    <TableCell>{t('app.status')}</TableCell>
                    <TableCell>{t('app.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {groupTools.map((tool) => (
                    <TableRow key={tool.id}>
                      <TableCell><code>{tool.name}</code></TableCell>
                      <TableCell>
                        <Typography variant="caption">{tool.description ?? '—'}</Typography>
                      </TableCell>
                      <TableCell>
                        <SkillChips toolId={tool.id} />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={tool.is_active ? t('app.active') : t('app.inactive')}
                          color={tool.is_active ? 'success' : 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        <Tooltip title="Test Tool">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => setTestingTool(tool)}
                          >
                            <PlayArrowIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        ))
      )}
      {!isLoading && !error && Object.keys(grouped).length === 0 && (
        <Typography color="text.secondary">{t('app.noData')}</Typography>
      )}

      {/* Test Tool Dialog */}
      <TestMcpToolDialog
        open={!!testingTool}
        tool={testingTool}
        onClose={() => setTestingTool(null)}
      />
    </Box>
  )
}
