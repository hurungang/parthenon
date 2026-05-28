import { useState } from 'react'
import {
  Box,
  Chip,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import BuildIcon from '@mui/icons-material/Build'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'
import { isWorkingStepSpan } from '../../services/LogPresenter'
import type { WorkingStep, WorkingStepSpan, WorkingStepIconType } from '../../types'

interface Props {
  spans: WorkingStepSpan[]
}

function StepIcon({ iconType }: { iconType: WorkingStepIconType }) {
  const color: Record<WorkingStepIconType, string> = {
    llm: '#7c4dff',
    tool: '#0288d1',
    success: '#2e7d32',
    error: '#c62828',
    info: '#546e7a',
  }
  const sx = { fontSize: 18, color: color[iconType] }
  switch (iconType) {
    case 'llm':
      return <AutoAwesomeIcon sx={sx} />
    case 'tool':
      return <BuildIcon sx={sx} />
    case 'success':
      return <CheckCircleOutlineIcon sx={sx} />
    case 'error':
      return <ErrorOutlineIcon sx={sx} />
    default:
      return <InfoOutlinedIcon sx={sx} />
  }
}

function StepRow({ step }: { step: WorkingStep }) {
  const [detailOpen, setDetailOpen] = useState(false)

  const formattedTime = new Date(step.timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  } as Intl.DateTimeFormatOptions)

  return (
    <Box>
      <Box display="flex" alignItems="center" gap={1} py={0.75}>
        <StepIcon iconType={step.iconType} />
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ minWidth: 80, fontFamily: 'monospace' }}
        >
          {formattedTime}
        </Typography>
        <Typography variant="body2" sx={{ flex: 1 }}>
          {step.message}
        </Typography>
        {step.detail && (
          <Tooltip title={detailOpen ? 'Collapse detail' : 'Expand detail'}>
            <IconButton
              size="small"
              onClick={() => setDetailOpen((v) => !v)}
              aria-expanded={detailOpen}
              aria-label={detailOpen ? 'Collapse detail' : 'Expand detail'}
            >
              <ExpandMoreIcon
                fontSize="small"
                sx={{
                  transform: detailOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s',
                }}
              />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      {step.detail && (
        <Collapse in={detailOpen}>
          <Box ml={4} mb={1}>
            <Chip
              label={step.detail.label}
              size="small"
              variant="outlined"
              sx={{ mb: 0.5, fontSize: '0.7rem' }}
            />
            <Box
              component="pre"
              sx={{
                bgcolor: 'grey.50',
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 1.5,
                fontSize: 12,
                fontFamily: 'monospace',
                overflow: 'auto',
                maxHeight: 240,
                m: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {step.detail.content}
            </Box>
          </Box>
        </Collapse>
      )}
    </Box>
  )
}

/** Renders a single span section (collapsible, with nested spans or leaf steps). */
function SpanSection({
  span,
  depth = 0,
}: {
  span: WorkingStepSpan
  depth?: number
}) {
  const [collapsed, setCollapsed] = useState(span.collapsed)

  const indentPx = depth * 16

  return (
    <Box>
      {/* Span header — toggle button */}
      <Box
        display="flex"
        alignItems="center"
        gap={0.75}
        py={0.75}
        pl={`${indentPx}px`}
        onClick={() => setCollapsed((v) => !v)}
        sx={{ cursor: 'pointer', userSelect: 'none' }}
        role="button"
        aria-expanded={!collapsed}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setCollapsed((v) => !v)
          }
        }}
      >
        <ExpandMoreIcon
          sx={{
            fontSize: 18,
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
            color: 'text.secondary',
          }}
        />
        <StepIcon iconType={span.iconType} />
        <Typography variant="subtitle2" fontWeight={600}>
          {span.title}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          ({span.children.length})
        </Typography>
      </Box>

      {/* Span children */}
      <Collapse in={!collapsed}>
        <Box
          sx={{
            ml: `${indentPx + 16}px`,
            borderLeft: 1,
            borderColor: 'divider',
            pl: 1,
            mb: 0.5,
          }}
        >
          <Stack divider={<Divider />}>
            {span.children.map((child) =>
              isWorkingStepSpan(child) ? (
                <SpanSection key={child.id} span={child} depth={depth + 1} />
              ) : (
                <StepRow key={child.id} step={child} />
              )
            )}
          </Stack>
        </Box>
      </Collapse>
    </Box>
  )
}

export function WorkingStepsPanel({ spans }: Props) {
  const { t } = useTranslation()
  const [sectionCollapsed, setSectionCollapsed] = useState(false)

  const totalSteps = spans.reduce(function countChildren(sum, s): number {
    return sum + s.children.reduce(
      (acc, child) =>
        isWorkingStepSpan(child)
          ? countChildren(acc, child)
          : acc + 1,
      0
    )
  }, 0)

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Box
        display="flex"
        alignItems="center"
        gap={1}
        mb={2}
        onClick={() => setSectionCollapsed((v) => !v)}
        sx={{ cursor: 'pointer', userSelect: 'none' }}
        role="button"
        aria-expanded={!sectionCollapsed}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setSectionCollapsed((v) => !v)
          }
        }}
      >
        <Typography variant="h6" fontWeight={600}>
          {t('agents.sessions.logViewer.workingSteps.title')}
        </Typography>
        {spans.length > 0 && (
          <Typography variant="body2" color="text.secondary">
            ({sectionCollapsed 
              ? t('agents.sessions.logViewer.workingSteps.showSteps', { count: totalSteps })
              : t('agents.sessions.logViewer.workingSteps.hideSteps')})
          </Typography>
        )}
      </Box>

      {spans.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.logViewer.workingSteps.empty')}
        </Typography>
      )}

      {spans.length > 0 && (
        <Collapse in={!sectionCollapsed}>
          <Stack divider={<Divider />}>
            {spans.map((span) => (
              <SpanSection key={span.id} span={span} />
            ))}
          </Stack>
        </Collapse>
      )}
    </Paper>
  )
}

