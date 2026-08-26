import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Typography,
  Paper,
  IconButton,
  Tooltip,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { API_CONFIG } from '../../api/API_CONFIG'

interface McpConnectionGuideProps {
  apiKey?: string
  defaultExpanded?: boolean
}

export function McpConnectionGuide({ apiKey, defaultExpanded = false }: McpConnectionGuideProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [copiedEndpoint, setCopiedEndpoint] = useState(false)
  const [copiedConfig, setCopiedConfig] = useState(false)
  const [copiedSseConfig, setCopiedSseConfig] = useState(false)

  const endpoint = API_CONFIG.MCP_ENDPOINT
  const key = apiKey ?? '<your-api-key>'

  const copilotConfig = JSON.stringify(
    {
      mcpServers: {
        parthenon: {
          type: 'http',
          url: endpoint,
          headers: {
            Authorization: `Bearer ${key}`,
          },
        },
      },
    },
    null,
    2,
  )

  const sseConfig = JSON.stringify(
    {
      mcpServers: {
        parthenon: {
          type: 'sse',
          url: `${endpoint}/sse`,
          headers: {
            Authorization: `Bearer ${key}`,
          },
        },
      },
    },
    null,
    2,
  )

  const copyText = async (text: string, setState: (v: boolean) => void) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setState(true)
    setTimeout(() => setState(false), 2000)
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Box display="flex" alignItems="center" gap={1} mb={1}>
        <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
          {t('apiKeys.mcpConnectionTitle')}
        </Typography>
        <Button size="small" onClick={() => setExpanded((v) => !v)}>
          {expanded ? t('apiKeys.hideInstructions') : t('apiKeys.showInstructions')}
        </Button>
      </Box>

      <Typography variant="caption" color="text.secondary">
        {t('apiKeys.mcpEndpointLabel')}
      </Typography>
      <Box display="flex" alignItems="center" gap={1}>
        <Typography fontFamily="monospace" fontSize="13px" sx={{ wordBreak: 'break-all', flex: 1 }}>
          {endpoint}
        </Typography>
        <Tooltip title={copiedEndpoint ? t('app.copied') : t('apiKeys.copyEndpoint')}>
          <IconButton size="small" onClick={() => copyText(endpoint, setCopiedEndpoint)}>
            <ContentCopyIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      {expanded && (
        <Box display="flex" flexDirection="column" gap={1.5} mt={1.5}>
          <Typography variant="caption" color="text.secondary">
            {t('apiKeys.mcpTransportNote')}
          </Typography>

          <Box>
            <Typography variant="caption" color="text.secondary">
              {t('apiKeys.mcpAuthHeaderLabel')}
            </Typography>
            <Typography fontFamily="monospace" fontSize="13px">
              Authorization: Bearer {key}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('apiKeys.mcpAuthQueryLabel')}
            </Typography>
            <Typography fontFamily="monospace" fontSize="13px" sx={{ wordBreak: 'break-all' }}>
              {endpoint}?apiKey={key}
            </Typography>
          </Box>

          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {t('apiKeys.mcpCopilotConfig')}
          </Typography>

          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
              {t('apiKeys.mcpConfigHttp')}
            </Typography>
            <Tooltip title={copiedConfig ? t('app.copied') : t('apiKeys.copyConfig')}>
              <IconButton size="small" onClick={() => copyText(copilotConfig, setCopiedConfig)}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          <Box
            component="pre"
            sx={{
              bgcolor: 'grey.900',
              color: 'common.white',
              p: 1.5,
              borderRadius: 1,
              fontSize: '12px',
              fontFamily: 'monospace',
              overflowX: 'auto',
              m: 0,
            }}
          >
            {copilotConfig}
          </Box>

          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
              {t('apiKeys.mcpConfigSse')}
            </Typography>
            <Tooltip title={copiedSseConfig ? t('app.copied') : t('apiKeys.copyConfig')}>
              <IconButton size="small" onClick={() => copyText(sseConfig, setCopiedSseConfig)}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
          <Box
            component="pre"
            sx={{
              bgcolor: 'grey.900',
              color: 'common.white',
              p: 1.5,
              borderRadius: 1,
              fontSize: '12px',
              fontFamily: 'monospace',
              overflowX: 'auto',
              m: 0,
            }}
          >
            {sseConfig}
          </Box>
        </Box>
      )}
    </Paper>
  )
}
