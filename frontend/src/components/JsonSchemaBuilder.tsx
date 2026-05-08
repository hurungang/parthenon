import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import CodeIcon from '@mui/icons-material/Code'
import EditIcon from '@mui/icons-material/Edit'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

type JsonType = 'string' | 'number' | 'boolean' | 'array' | 'object'

interface SchemaField {
  id: string
  name: string
  type: JsonType
  description: string
  required: boolean
}

interface JsonSchemaBuilderProps {
  value: string // JSON schema as string
  onChange: (schema: string) => void
  label?: string
  helperText?: string
}

/**
 * Visual builder for JSON schemas - allows users to define schema fields
 * with a form interface instead of raw JSON editing.
 * 
 * Supports basic JSON types: string, number, boolean, array, object.
 * Generates JSON Schema-compatible output.
 */
export function JsonSchemaBuilder({ value, onChange, label, helperText }: JsonSchemaBuilderProps) {
  const { t } = useTranslation()
  const [showRawJson, setShowRawJson] = useState(false)
  const [rawJsonInput, setRawJsonInput] = useState(value)

  // Parse existing schema into fields
  const parseSchema = (schemaStr: string): SchemaField[] => {
    if (!schemaStr.trim()) return []
    
    try {
      const schema = JSON.parse(schemaStr)
      const properties = schema.properties || {}
      const required = schema.required || []
      
      return Object.entries(properties).map(([name, def]: [string, any]) => ({
        id: Math.random().toString(36).substr(2, 9),
        name,
        type: def.type || 'string',
        description: def.description || '',
        required: required.includes(name),
      }))
    } catch {
      return []
    }
  }

  // Generate JSON schema from fields
  const generateSchema = (fields: SchemaField[]): string => {
    if (fields.length === 0) return ''
    
    const properties: Record<string, any> = {}
    const required: string[] = []
    
    fields.forEach(field => {
      properties[field.name] = {
        type: field.type,
        ...(field.description && { description: field.description }),
      }
      if (field.required) {
        required.push(field.name)
      }
    })
    
    const schema = {
      type: 'object',
      properties,
      ...(required.length > 0 && { required }),
    }
    
    return JSON.stringify(schema, null, 2)
  }

  const [fields, setFields] = useState<SchemaField[]>(() => parseSchema(value))

  const handleFieldsChange = (newFields: SchemaField[]) => {
    setFields(newFields)
    const newSchema = generateSchema(newFields)
    setRawJsonInput(newSchema)
    onChange(newSchema)
  }

  const addField = () => {
    const newField: SchemaField = {
      id: Math.random().toString(36).substr(2, 9),
      name: '',
      type: 'string',
      description: '',
      required: false,
    }
    handleFieldsChange([...fields, newField])
  }

  const removeField = (id: string) => {
    handleFieldsChange(fields.filter(f => f.id !== id))
  }

  const updateField = (id: string, updates: Partial<SchemaField>) => {
    handleFieldsChange(
      fields.map(f => f.id === id ? { ...f, ...updates } : f)
    )
  }

  const handleRawJsonSave = () => {
    try {
      JSON.parse(rawJsonInput) // Validate JSON
      onChange(rawJsonInput)
      setFields(parseSchema(rawJsonInput))
      setShowRawJson(false)
    } catch (error) {
      alert('Invalid JSON: ' + (error as Error).message)
    }
  }

  if (showRawJson) {
    return (
      <Box>
        {label && (
          <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
            {label}
          </Typography>
        )}
        <Stack spacing={1}>
          <TextField
            value={rawJsonInput}
            onChange={(e) => setRawJsonInput(e.target.value)}
            fullWidth
            multiline
            rows={8}
            placeholder='{"type": "object", "properties": {...}}'
            inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
          />
          <Stack direction="row" spacing={1}>
            <Button size="small" onClick={handleRawJsonSave} variant="contained">
              {t('common.save')}
            </Button>
            <Button size="small" onClick={() => setShowRawJson(false)}>
              {t('common.cancel')}
            </Button>
          </Stack>
        </Stack>
        {helperText && (
          <Typography variant="caption" color="text.secondary" mt={0.5}>
            {helperText}
          </Typography>
        )}
      </Box>
    )
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1}>
        {label && (
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
        )}
        <Tooltip title={t('agents.types.schemaBuilder.editRawJson')}>
          <IconButton size="small" onClick={() => setShowRawJson(true)}>
            <CodeIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Stack spacing={2}>
        {fields.length === 0 && (
          <Paper variant="outlined" sx={{ p: 2, textAlign: 'center', bgcolor: 'background.default' }}>
            <Typography variant="body2" color="text.secondary">
              {t('agents.types.schemaBuilder.noFields')}
            </Typography>
          </Paper>
        )}

        {fields.map((field) => (
          <Paper key={field.id} variant="outlined" sx={{ p: 2 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={2} alignItems="flex-start">
                <TextField
                  label={t('agents.types.schemaBuilder.fieldName')}
                  value={field.name}
                  onChange={(e) => updateField(field.id, { name: e.target.value })}
                  size="small"
                  sx={{ flex: 1 }}
                  placeholder="fieldName"
                />
                
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel>{t('agents.types.schemaBuilder.type')}</InputLabel>
                  <Select
                    value={field.type}
                    label={t('agents.types.schemaBuilder.type')}
                    onChange={(e) => updateField(field.id, { type: e.target.value as JsonType })}
                  >
                    <MenuItem value="string">{t('agents.types.schemaBuilder.typeString')}</MenuItem>
                    <MenuItem value="number">{t('agents.types.schemaBuilder.typeNumber')}</MenuItem>
                    <MenuItem value="boolean">{t('agents.types.schemaBuilder.typeBoolean')}</MenuItem>
                    <MenuItem value="array">{t('agents.types.schemaBuilder.typeArray')}</MenuItem>
                    <MenuItem value="object">{t('agents.types.schemaBuilder.typeObject')}</MenuItem>
                  </Select>
                </FormControl>

                <Tooltip title={t('common.delete')}>
                  <IconButton size="small" onClick={() => removeField(field.id)} color="error">
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>

              <TextField
                label={t('agents.types.schemaBuilder.description')}
                value={field.description}
                onChange={(e) => updateField(field.id, { description: e.target.value })}
                size="small"
                fullWidth
                placeholder={t('agents.types.schemaBuilder.descriptionPlaceholder')}
              />

              <FormControlLabel
                control={
                  <Checkbox
                    checked={field.required}
                    onChange={(e) => updateField(field.id, { required: e.target.checked })}
                    size="small"
                  />
                }
                label={t('agents.types.schemaBuilder.required')}
              />
            </Stack>
          </Paper>
        ))}

        <Button
          startIcon={<AddIcon />}
          onClick={addField}
          variant="outlined"
          size="small"
          sx={{ alignSelf: 'flex-start' }}
        >
          {t('agents.types.schemaBuilder.addField')}
        </Button>
      </Stack>

      {helperText && (
        <Typography variant="caption" color="text.secondary" display="block" mt={1}>
          {helperText}
        </Typography>
      )}
    </Box>
  )
}
