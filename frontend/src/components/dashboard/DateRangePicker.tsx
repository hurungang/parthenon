import { useState, useEffect, useMemo } from 'react'
import { Box, Button, ButtonGroup, TextField } from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useTranslation } from 'react-i18next'

export interface DateRangePickerProps {
  startTime: Date | null
  endTime: Date | null
  onChange: (start: Date, end: Date) => void
  isRefreshing?: boolean
}

type PresetKey = 'hour' | 'day' | 'week'

function toLocalISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatRangeLabel(start: Date, end: Date): string {
  const opts: Intl.DateTimeFormatOptions = {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }
  return `${start.toLocaleDateString('en-US', opts)} \u2014 ${end.toLocaleDateString('en-US', opts)}`
}

function getActivePreset(start: Date | null, end: Date | null): PresetKey | null {
  if (!start || !end) return null
  const durH = (end.getTime() - start.getTime()) / (1000 * 60 * 60)
  if (durH >= 0.95 && durH <= 1.05) return 'hour'
  if (durH >= 23.5 && durH <= 24.5) return 'day'
  if (durH >= 165 && durH <= 170) return 'week'
  return null
}

export function DateRangePicker({
  startTime,
  endTime,
  onChange,
  isRefreshing = false,
}: DateRangePickerProps) {
  const { t } = useTranslation()

  // Draft state — updated as user types, only committed on "Go" or preset
  const [draftStart, setDraftStart] = useState<Date | null>(startTime)
  const [draftEnd, setDraftEnd] = useState<Date | null>(endTime)

  // Sync draft from props when props change (e.g. after a fetch)
  useEffect(() => {
    setDraftStart(startTime)
    setDraftEnd(endTime)
  }, [startTime, endTime])

  const hasChanges = useMemo(() => {
    if (!draftStart || !draftEnd || !startTime || !endTime) return false
    return draftStart.getTime() !== startTime.getTime() || draftEnd.getTime() !== endTime.getTime()
  }, [draftStart, draftEnd, startTime, endTime])

  const activePreset = useMemo(
    () => getActivePreset(draftStart, draftEnd),
    [draftStart, draftEnd],
  )

  const rangeLabel = useMemo(() => {
    if (!draftStart || !draftEnd) return ''
    return formatRangeLabel(draftStart, draftEnd)
  }, [draftStart, draftEnd])

  const startISO = draftStart ? toLocalISO(draftStart) : ''
  const endISO = draftEnd ? toLocalISO(draftEnd) : ''

  function commit(newStart: Date, newEnd: Date) {
    onChange(newStart, newEnd)
  }

  function handlePreset(key: PresetKey) {
    const now = new Date()
    let start: Date
    switch (key) {
      case 'hour':
        start = new Date(now.getTime() - 1 * 60 * 60 * 1000)
        break
      case 'day':
        start = new Date(now.getTime() - 24 * 60 * 60 * 1000)
        break
      case 'week':
        start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
        break
    }
    setDraftStart(start)
    setDraftEnd(now)
    commit(start, now)
  }

  function handleStartChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    if (!val) return
    const dt = new Date(val)
    if (isNaN(dt.getTime())) return
    setDraftStart(dt)
  }

  function handleEndChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    if (!val) return
    const dt = new Date(val)
    if (isNaN(dt.getTime())) return
    setDraftEnd(dt)
  }

  function handleGo() {
    if (draftStart && draftEnd) {
      commit(draftStart, draftEnd)
    }
  }

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 1.5,
        mb: 2,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <TextField
          label={t('dashboard.from')}
          type="datetime-local"
          size="small"
          value={startISO}
          onChange={handleStartChange}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 220 }}
        />

        <Box sx={{ color: 'text.secondary', fontSize: 13 }}>&mdash;</Box>

        <TextField
          label={t('dashboard.to')}
          type="datetime-local"
          size="small"
          value={endISO}
          onChange={handleEndChange}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 220 }}
        />

        {hasChanges && (
          <Button
            size="small"
            variant="contained"
            startIcon={<PlayArrowIcon />}
            onClick={handleGo}
          >
            {t('dashboard.go')}
          </Button>
        )}

        <ButtonGroup size="small" variant="outlined" sx={{ ml: 0.5 }}>
          <Button
            variant={activePreset === 'hour' ? 'contained' : 'outlined'}
            onClick={() => handlePreset('hour')}
          >
            {t('dashboard.presetHour')}
          </Button>
          <Button
            variant={activePreset === 'day' ? 'contained' : 'outlined'}
            onClick={() => handlePreset('day')}
          >
            {t('dashboard.preset24h')}
          </Button>
          <Button
            variant={activePreset === 'week' ? 'contained' : 'outlined'}
            onClick={() => handlePreset('week')}
          >
            {t('dashboard.preset7d')}
          </Button>
        </ButtonGroup>
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
        {rangeLabel && (
          <Box sx={{ fontSize: 12, color: 'text.secondary' }}>{rangeLabel}</Box>
        )}
        <Button
          size="small"
          variant="outlined"
          startIcon={<RefreshIcon />}
          disabled={isRefreshing}
          onClick={() => {
            if (startTime && endTime) commit(new Date(startTime), new Date(endTime))
          }}
        >
          {t('app.refresh')}
        </Button>
      </Box>
    </Box>
  )
}
