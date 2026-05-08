import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface JsonSchema {
  type: 'object'
  properties?: Record<string, {
    type: 'string' | 'number' | 'boolean' | 'array' | 'object'
    description?: string
  }>
  required?: string[]
}

interface DynamicSchemaFormProps {
  schema: string | JsonSchema // Can be JSON string or parsed object
  value: Record<string, any>
  onChange: (value: Record<string, any>) => void
  error?: string | null
}

/**
 * Dynamically renders form fields based on a JSON Schema.
 * Supports basic types: string, number, boolean, array, object.
 * 
 * For typed agent input, this provides a user-friendly alternative
 * to raw JSON editing.
 */
export function DynamicSchemaForm({ schema, value, onChange, error }: DynamicSchemaFormProps) {
  const { t } = useTranslation()
  const [parsedSchema, setParsedSchema] = useState<JsonSchema | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)

  useEffect(() => {
    try {
      if (typeof schema === 'string') {
        if (!schema.trim()) {
          setParsedSchema(null)
          setParseError(null)
          return
        }
        const parsed = JSON.parse(schema) as JsonSchema
        setParsedSchema(parsed)
        setParseError(null)
      } else {
        setParsedSchema(schema)
        setParseError(null)
      }
    } catch (err) {
      setParsedSchema(null)
      setParseError((err as Error).message)
    }
  }, [schema])

  if (parseError) {
    return (
      <Box sx={{ p: 2, bgcolor: 'error.50', borderRadius: 1 }}>
        <Typography variant="body2" color="error">
          {t('agents.sessions.schemaParseError')}: {parseError}
        </Typography>
      </Box>
    )
  }

  if (!parsedSchema || !parsedSchema.properties) {
    return (
      <Box sx={{ p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.noSchemaFields')}
        </Typography>
      </Box>
    )
  }

  const properties = parsedSchema.properties
  const requiredFields = parsedSchema.required || []

  const handleFieldChange = (fieldName: string, fieldValue: any) => {
    onChange({ ...value, [fieldName]: fieldValue })
  }

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      {error && (
        <Typography variant="body2" color="error">
          {error}
        </Typography>
      )}
      
      {Object.entries(properties)
        .filter(([_, fieldDef]) => fieldDef && fieldDef.type) // Filter out invalid entries
        .map(([fieldName, fieldDef]) => {
        // Additional runtime safety check
        if (!fieldDef || !fieldDef.type) {
          console.warn('DynamicSchemaForm: Filtered fieldDef is still undefined:', fieldName)
          return null
        }
        
        const isRequired = requiredFields.includes(fieldName)
        const fieldValue = value[fieldName]

        switch (fieldDef.type) {
          case 'string':
            return (
              <TextField
                key={fieldName}
                label={fieldName}
                value={fieldValue || ''}
                onChange={(e) => handleFieldChange(fieldName, e.target.value)}
                fullWidth
                required={isRequired}
                helperText={fieldDef.description}
                size="small"
              />
            )

          case 'number':
            return (
              <TextField
                key={fieldName}
                label={fieldName}
                type="number"
                value={fieldValue ?? ''}
                onChange={(e) => {
                  const val = e.target.value
                  handleFieldChange(fieldName, val === '' ? undefined : Number(val))
                }}
                fullWidth
                required={isRequired}
                helperText={fieldDef.description}
                size="small"
              />
            )

          case 'boolean':
            return (
              <FormControl key={fieldName} fullWidth>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={fieldValue === true}
                      onChange={(e) => handleFieldChange(fieldName, e.target.checked)}
                    />
                  }
                  label={
                    <Box>
                      <Typography variant="body2">
                        {fieldName}
                        {isRequired && <Typography component="span" color="error"> *</Typography>}
                      </Typography>
                      {fieldDef.description && (
                        <Typography variant="caption" color="text.secondary">
                          {fieldDef.description}
                        </Typography>
                      )}
                    </Box>
                  }
                />
              </FormControl>
            )

          case 'array':
          case 'object':
            // For complex types, fall back to JSON input
            return (
              <Box key={fieldName}>
                <Typography variant="body2" fontWeight="medium" mb={0.5}>
                  {fieldName}
                  {isRequired && <Typography component="span" color="error"> *</Typography>}
                </Typography>
                {fieldDef.description && (
                  <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                    {fieldDef.description}
                  </Typography>
                )}
                <TextField
                  value={
                    fieldValue !== undefined
                      ? typeof fieldValue === 'string'
                        ? fieldValue
                        : JSON.stringify(fieldValue, null, 2)
                      : ''
                  }
                  onChange={(e) => {
                    const val = e.target.value
                    try {
                      const parsed = val.trim() ? JSON.parse(val) : undefined
                      handleFieldChange(fieldName, parsed)
                    } catch {
                      // Keep as string if invalid JSON
                      handleFieldChange(fieldName, val)
                    }
                  }}
                  fullWidth
                  multiline
                  rows={3}
                  placeholder={fieldDef.type === 'array' ? '[]' : '{}'}
                  inputProps={{ style: { fontFamily: 'monospace', fontSize: 12 } }}
                  size="small"
                />
              </Box>
            )

          default:
            return null
        }
      })}
    </Box>
  )
}
