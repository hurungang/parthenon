import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { DynamicSchemaForm } from '../../components/DynamicSchemaForm'

interface McpSession {
  id: string
  name: string
  server_id: string
}

interface McpTool {
  id: string
  name: string
  original_name: string
  description: string | null
  input_schema: Record<string, any> | null
  server_id: string
}

interface TestMcpToolDialogProps {
  open: boolean
  tool: McpTool | null
  onClose: () => void
}

export function TestMcpToolDialog({ open, tool, onClose }: TestMcpToolDialogProps) {
  const { t } = useTranslation()
  const [selectedSessionId, setSelectedSessionId] = useState<string>('')
  const [typedInputData, setTypedInputData] = useState<Record<string, any>>({})
  const [rawJsonInput, setRawJsonInput] = useState<string>('{}')
  const [useRawJson, setUseRawJson] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Extract and format MCP response data
  const formatMcpResponse = (response: any): string => {
    try {
      // MCP protocol wraps data in content array with text field containing JSON string
      if (response?.content?.[0]?.text) {
        const parsedData = JSON.parse(response.content[0].text)
        return JSON.stringify(parsedData, null, 2)
      }
      // Fallback to raw response
      return JSON.stringify(response, null, 2)
    } catch (e) {
      // If parsing fails, return as-is
      return JSON.stringify(response, null, 2)
    }
  }

  // Fetch sessions for the tool's server
  const { data: sessions, isLoading: loadingSessions } = useQuery<McpSession[]>({
    queryKey: ['mcp', 'servers', tool?.server_id, 'sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSession[]>(`/mcp/servers/${tool!.server_id}/sessions`)
      return data
    },
    enabled: open && !!tool,
  })

  const handleTest = async () => {
    if (!tool || !selectedSessionId) return

    setTesting(true)
    setError(null)
    setTestResult(null)

    try {
      let inputData: Record<string, any>

      if (useRawJson) {
        try {
          inputData = JSON.parse(rawJsonInput)
        } catch (e) {
          setError(t('agents.sessions.invalidJson'))
          setTesting(false)
          return
        }
      } else {
        inputData = typedInputData
      }

      const { data } = await apiClient.post(`/mcp/tools/${tool.id}/test`, {
        session_id: selectedSessionId,
        tool_input: inputData,
      })

      setTestResult(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Test failed')
    } finally {
      setTesting(false)
    }
  }

  const handleClose = () => {
    setSelectedSessionId('')
    setTypedInputData({})
    setRawJsonInput('{}')
    setTestResult(null)
    setError(null)
    setUseRawJson(false)
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        Test Tool: {tool?.name}
      </DialogTitle>

      <DialogContent dividers>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Box display="flex" flexDirection="column" gap={2}>
          {/* Tool Info */}
          <Box>
            <Typography variant="subtitle2">Tool Information</Typography>
            <Typography variant="body2" color="text.secondary">
              {tool?.description || 'No description available'}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
              {tool?.original_name}
            </Typography>
          </Box>

          {/* Session Selection */}
          <FormControl fullWidth>
            <InputLabel>MCP Session</InputLabel>
            <Select
              value={selectedSessionId}
              onChange={(e) => setSelectedSessionId(e.target.value)}
              label="MCP Session"
              disabled={loadingSessions}
            >
              {(sessions ?? []).map((session) => (
                <MenuItem key={session.id} value={session.id}>
                  {session.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* Input Form */}
          {tool?.input_schema ? (
            <Box>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
                <Typography variant="subtitle2">Tool Input</Typography>
                <Button
                  size="small"
                  onClick={() => setUseRawJson(!useRawJson)}
                >
                  {useRawJson ? t('agents.sessions.useFormInput') : t('agents.sessions.useRawJson')}
                </Button>
              </Box>

              {useRawJson ? (
                <TextField
                  fullWidth
                  multiline
                  rows={8}
                  value={rawJsonInput}
                  onChange={(e) => setRawJsonInput(e.target.value)}
                  placeholder={JSON.stringify(tool.input_schema, null, 2)}
                  sx={{ fontFamily: 'monospace', fontSize: '0.875rem' }}
                />
              ) : (
                <DynamicSchemaForm
                  schema={JSON.stringify(tool.input_schema)}
                  value={typedInputData}
                  onChange={setTypedInputData}
                />
              )}
            </Box>
          ) : (
            <Alert severity="info">No input schema defined for this tool</Alert>
          )}

          {/* Test Result */}
          {testResult && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Test Result
              </Typography>
              {testResult.success ? (
                <Box>
                  <Alert severity="success" sx={{ mb: 1 }}>
                    Tool invocation successful
                  </Alert>
                  <TextField
                    fullWidth
                    multiline
                    rows={12}
                    value={formatMcpResponse(testResult.raw_response || testResult.result)}
                    InputProps={{ readOnly: true }}
                    sx={{ fontFamily: 'monospace', fontSize: '0.875rem' }}
                  />
                </Box>
              ) : (
                <Alert severity="error">
                  <Typography variant="body2" fontWeight="bold">Error:</Typography>
                  <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                    {testResult.error}
                  </Typography>
                </Alert>
              )}
            </Box>
          )}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={handleClose}>{t('app.close')}</Button>
        <Button
          variant="contained"
          onClick={handleTest}
          disabled={!selectedSessionId || testing}
        >
          {testing ? 'Testing...' : 'Test Tool'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
