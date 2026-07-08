import type { ReactNode } from 'react'
import { Box, Card, CardActionArea, CardContent, Skeleton, Typography } from '@mui/material'
import LockIcon from '@mui/icons-material/Lock'
import { useTranslation } from 'react-i18next'

export interface SubBreakdown {
  label: string
  color?: string
}

export type CardColorVariant =
  | 'blue'
  | 'green'
  | 'purple'
  | 'orange'
  | 'red'
  | 'teal'
  | 'amber'
  | 'slate'

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

export interface StatCardProps {
  icon: ReactNode
  label: string
  value: number
  subLabel?: string
  subBreakdowns?: SubBreakdown[]
  isLoading: boolean
  isPermissionDenied: boolean
  colorVariant?: CardColorVariant
  navigateTo?: string
}

export function StatCard({
  icon,
  label,
  value,
  subLabel,
  subBreakdowns,
  isLoading,
  isPermissionDenied,
  colorVariant = 'blue',
  navigateTo,
}: StatCardProps) {
  const { t } = useTranslation()
  const iconColor = ICON_COLORS[colorVariant]
  const isZero = value === 0 && !isLoading && !isPermissionDenied
  const isClickable = !!navigateTo && !isLoading && !isPermissionDenied

  const content = (
    <>
      {isPermissionDenied && (
        <Box
          sx={{
            position: 'absolute',
            top: 0, left: 0, right: 0, bottom: 0,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            gap: 0.75, zIndex: 2,
          }}
        >
          <LockIcon sx={{ fontSize: 24, color: '#EF4444' }} />
          <Typography variant="caption" sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, color: '#EF4444', fontSize: 11 }}>
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
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, color: iconColor, flexShrink: 0, lineHeight: 0 }}>
              {icon}
            </Box>
          )}
          {isLoading ? (
            <Skeleton width={80} height={14} />
          ) : (
            <Typography variant="caption" sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: 'text.secondary', flex: 1 }}>
              {label}
            </Typography>
          )}
        </Box>

        {isLoading ? (
          <Skeleton width={48} height={28} />
        ) : !isPermissionDenied ? (
          <Typography variant="h5" sx={{ fontWeight: isZero ? 400 : 700, color: isZero ? 'text.secondary' : 'text.primary', lineHeight: 1, mb: 0.5, fontSize: '1.25rem' }}>
            {value}
          </Typography>
        ) : null}

        {!isLoading && !isPermissionDenied && (subBreakdowns || subLabel) && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
            {subBreakdowns?.map((b) => (
              <Box key={b.label} sx={{ display: 'inline-flex', alignItems: 'center', px: 0.75, py: 0.125, borderRadius: 8, fontSize: 10, fontWeight: 500, bgcolor: b.color ? `${b.color}20` : '#F1F5F9', color: b.color ?? '#475569' }}>
                {b.label}
              </Box>
            ))}
            {subLabel && <Typography variant="caption" color="text.secondary" sx={{ fontSize: 10 }}>{subLabel}</Typography>}
          </Box>
        )}
      </CardContent>
    </>
  )

  return (
    <Card
      sx={{
        height: '100%',
        minHeight: 120,
        borderRadius: 2,
        border: isPermissionDenied ? '1px dashed #EF4444' : '1px solid',
        borderColor: isPermissionDenied ? undefined : 'divider',
        boxShadow: 1,
        bgcolor: isPermissionDenied ? '#FFF5F5' : undefined,
        opacity: isPermissionDenied ? 0.7 : 1,
        position: 'relative',
        overflow: 'hidden',
        transition: 'box-shadow 0.2s ease, opacity 0.2s ease',
        '&:hover': { boxShadow: 3 },
      }}
    >
      {isClickable ? (
        <CardActionArea href={navigateTo} sx={{ height: '100%' }}>
          {content}
        </CardActionArea>
      ) : (
        content
      )}
    </Card>
  )
}
