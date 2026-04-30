import { Alert, Box, Button } from '@mui/material'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage, extractPermissionError } from '../../utils/errorUtils'
import LockIcon from '@mui/icons-material/Lock'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'

interface PermissionDeniedAlertProps {
  error: unknown
  fallbackMessage?: string
}

/**
 * Displays a permission denied error with structured details (resource type, action, resource ID)
 * and a link to request access.
 */
export default function PermissionDeniedAlert({ 
  error, 
  fallbackMessage = 'Permission denied' 
}: PermissionDeniedAlertProps) {
  const { t } = useTranslation()
  
  const permError = extractPermissionError(error)
  
  if (permError) {
    const { required_permission } = permError
    const resourceIdText = required_permission.resource_id 
      ? ` (ID: ${required_permission.resource_id})` 
      : ''
    
    return (
      <Alert 
        severity="error" 
        icon={<LockIcon />}
        sx={{ 
          mb: 2,
          '& .MuiAlert-message': { 
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap'
          }
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1, flexWrap: 'wrap' }}>
          <Box component="span" sx={{ fontWeight: 600, fontSize: '0.875rem' }}>
            Permission Denied:
          </Box>
          <Box component="span" sx={{ fontSize: '0.875rem' }}>
            <strong>Action:</strong> {required_permission.action}
            {' • '}
            <strong>Resource:</strong> {required_permission.resource_type}
            {resourceIdText}
          </Box>
        </Box>
        <Button
          component={Link}
          to="/permissions/access-requests"
          variant="outlined"
          size="small"
          endIcon={<OpenInNewIcon />}
          sx={{ flexShrink: 0, ml: 'auto' }}
        >
          {t('permissions.requestAccess', 'Request Access')}
        </Button>
      </Alert>
    )
  }
  
  // Fallback to generic error message
  const message = extractErrorMessage(error, fallbackMessage)
  return (
    <Alert severity="error" sx={{ mb: 2 }}>
      {message}
    </Alert>
  )
}
