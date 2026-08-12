import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  IconButton,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline'

interface PayloadEditorProps {
  value: Record<string, string>
  onChange: (payload: Record<string, string>) => void
}

interface Entry {
  key: string
  value: string
}

function entriesFromRecord(record: Record<string, string>): Entry[] {
  return Object.entries(record).map(([k, v]) => ({ key: k, value: v }))
}

function recordFromEntries(entries: Entry[]): Record<string, string> {
  const result: Record<string, string> = {}
  for (const entry of entries) {
    if (entry.key.trim()) {
      result[entry.key.trim()] = entry.value
    }
  }
  return result
}

export default function PayloadEditor({ value, onChange }: PayloadEditorProps) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<Entry[]>(() => entriesFromRecord(value))

  const handleChange = (entries: Entry[]) => {
    setEntries(entries)
    onChange(recordFromEntries(entries))
  }

  const updateEntry = (index: number, field: 'key' | 'value', val: string) => {
    const updated = entries.map((entry, i) =>
      i === index ? { ...entry, [field]: val } : entry,
    )
    handleChange(updated)
  }

  const addEntry = () => {
    handleChange([...entries, { key: '', value: '' }])
  }

  const removeEntry = (index: number) => {
    handleChange(entries.filter((_, i) => i !== index))
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {t('schedules.payloadEditor')}
      </Typography>
      {entries.map((entry, index) => (
        <Box key={index} display="flex" gap={1} alignItems="center" mb={1}>
          <TextField
            size="small"
            placeholder={t('schedules.key')}
            value={entry.key}
            onChange={(e) => updateEntry(index, 'key', e.target.value)}
            sx={{ flex: 1 }}
          />
          <TextField
            size="small"
            placeholder={t('schedules.value')}
            value={entry.value}
            onChange={(e) => updateEntry(index, 'value', e.target.value)}
            sx={{ flex: 1 }}
          />
          <IconButton size="small" color="error" onClick={() => removeEntry(index)}>
            <RemoveCircleOutlineIcon />
          </IconButton>
        </Box>
      ))}
      <Button size="small" startIcon={<AddIcon />} onClick={addEntry}>
        {t('schedules.addParameter')}
      </Button>
    </Box>
  )
}
