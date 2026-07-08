import type { ReactNode } from 'react'
import { Box, Card, CardContent, Skeleton, Typography } from '@mui/material'
import LockIcon from '@mui/icons-material/Lock'
import { useTranslation } from 'react-i18next'
import type { CardColorVariant } from './StatCard'

const ICON_COLORS: Record<CardColorVariant, string> = {
  blue: '#1D4ED8',
  green: '#15803D',
  purple: '#6D28D9',
  orange: '#C2410C',
  red: '#B91C1C',
  teal: '#065F46',
  amber: '#92400E',
  slate: '#475569',
}

export interface TimeSensitiveCardProps {
  variant: 'single' | 'dual'
  icon: ReactNode
  label: string
  value?: number
  completed?: number
  failed?: number
  isLoading: boolean
  isPermissionDenied: boolean
  colorVariant?: CardColorVariant
}

export function TimeSensitiveCard({
  variant,
  icon,
  label,
  value = 0,
  completed = 0,
  failed = 0,
  isLoading,
  isPermissionDenied,
  colorVariant = 'blue',
}: TimeSensitiveCardProps) {
  const { t } = useTranslation()
  const iconColor = ICON_COLORS[colorVariant]

  const isZero = !isLoading && !isPermissionDenied && (
    variant === 'single' ? value === 0 : (completed === 0 && failed === 0)
  )

  return (
    <Card
      sx={{
        height: '100%',
        minHeight: 120,
        borderRadius: 2,
        border: isPermissionDenied
          ? '1px dashed #EF4444'
          : '1px solid',
        borderColor: isPermissionDenied ? undefined : 'divider',
        borderLeft: isPermissionDenied ? undefined : `3px solid ${iconColor}`,
        boxShadow: 1,
        bgcolor: isPermissionDenied ? '#FFF5F5' : undefined,
        opacity: isPermissionDenied ? 0.7 : 1,
        position: 'relative',
        overflow: 'hidden',
        transition: 'box-shadow 0.2s ease, opacity 0.2s ease',
        '&:hover': { boxShadow: 3 },
      }}
    >
      {isPermissionDenied && (
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 0.75,
            zIndex: 2,
          }}
        >
          <LockIcon sx={{ fontSize: 24, color: '#EF4444' }} />
          <Typography
            variant="caption"
            sx={{
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: 0.5,
              color: '#EF4444',
              fontSize: 11,
            }}
          >
            {t('permissions.errors.accessDeniedTitle')}
          </Typography>
        </Box>
      )}

      <CardContent
        sx={{
          p: '12px 16px !important',
          pb: '12px !important',
          filter: isPermissionDenied ? 'blur(2px)' : undefined,
          pointerEvents: isPermissionDenied ? 'none' : undefined,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75 }}>
          {isLoading ? (
            <Skeleton variant="circular" width={24} height={24} />
          ) : (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 20,
                color: iconColor,
                flexShrink: 0,
                lineHeight: 0,
              }}
            >
              {icon}
            </Box>
          )}
          {isLoading ? (
            <Skeleton width={100} height={14} />
          ) : (
            <Typography
              variant="caption"
              sx={{
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                color: 'text.secondary',
                flex: 1,
              }}
            >
              {label}
            </Typography>
          )}
        </Box>

        <Box>
          {isLoading ? (
            <Skeleton width={variant === 'dual' ? 90 : 48} height={28} />
          ) : !isPermissionDenied ? (
            variant === 'dual' ? (
              <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75 }}>
                <Typography
                  variant="h5"
                  sx={{
                    fontWeight: isZero ? 400 : 700,
                    color: isZero ? 'text.secondary' : '#4CAF50',
                    lineHeight: 1,
                    fontSize: '1.25rem',
                  }}
                >
                  {completed}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 300, color: 'text.secondary' }}>
                  /
                </Typography>
                <Typography
                  variant="h5"
                  sx={{
                    fontWeight: isZero ? 400 : 700,
                    color: isZero ? 'text.secondary' : '#F44336',
                    lineHeight: 1,
                    fontSize: '1.25rem',
                  }}
                >
                  {failed}
                </Typography>
              </Box>
            ) : (
              <Typography
                variant="h5"
                sx={{
                  fontWeight: isZero ? 400 : 700,
                  color: isZero ? 'text.secondary' : 'text.primary',
                  lineHeight: 1,
                  fontSize: '1.25rem',
                }}
              >
                {value}
              </Typography>
            )
          ) : null}
        </Box>
      </CardContent>
    </Card>
  )
}
