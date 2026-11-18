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

/**
 * Health tone of a dashboard tile. Drives the card tint / border highlight and
 * the `data-status-tone` attribute used by the severity-ranked dashboard layout.
 */
export type CardStatusTone = 'success' | 'warning' | 'error'

const STATUS_TONE_STYLES: Record<
  CardStatusTone,
  { bgcolor: string; borderColor: string }
> = {
  success: { bgcolor: '#F0FDF4', borderColor: '#BBF7D0' },
  warning: { bgcolor: '#FFFBEB', borderColor: '#FDE68A' },
  error: { bgcolor: '#FEF2F2', borderColor: '#FECACA' },
}

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
  /** Card health tone (`neutral` when omitted). */
  statusTone?: CardStatusTone
  /** Renders the "Action required" badge and the action-highlight styling. */
  actionRequired?: boolean
}

/**
 * Small "Action required" pill rendered in the top-right of an actionable card.
 * Kept inside the header row (not absolutely positioned) so it never overlaps
 * the icon or the label.
 */
export function ActionRequiredBadge({ tone }: { tone?: CardStatusTone }) {
  const { t } = useTranslation()
  const color =
    tone === 'warning' ? '#B45309' : tone === 'success' ? '#15803D' : '#B91C1C'

  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        flexShrink: 0,
        px: 0.75,
        py: 0.125,
        borderRadius: 8,
        fontSize: 10,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: 0.4,
        whiteSpace: 'nowrap',
        bgcolor: tone ? STATUS_TONE_STYLES[tone].borderColor : '#E2E8F0',
        color,
      }}
    >
      {t('dashboard.actionRequired')}
    </Box>
  )
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
  statusTone,
  actionRequired = false,
}: StatCardProps) {
  const { t } = useTranslation()
  const iconColor = ICON_COLORS[colorVariant]
  const isZero = value === 0 && !isLoading && !isPermissionDenied
  const isClickable = !!navigateTo && !isLoading && !isPermissionDenied

  // Permission-denied visuals always win over the action highlight.
  const actionHighlight =
    actionRequired && !isPermissionDenied && !!statusTone
      ? STATUS_TONE_STYLES[statusTone]
      : undefined
  const showActionBadge = actionRequired && !isPermissionDenied && !isLoading

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
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          filter: isPermissionDenied ? 'blur(2px)' : undefined,
          pointerEvents: isPermissionDenied ? 'none' : undefined,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 0.75, minHeight: 40 }}>
          {isLoading ? (
            <Skeleton variant="circular" width={24} height={24} />
          ) : (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, color: iconColor, flexShrink: 0, lineHeight: 0, mt: 0.25 }}>
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
          {showActionBadge && <ActionRequiredBadge tone={statusTone} />}
        </Box>

        <Box sx={{ mt: 'auto' }}>
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
        </Box>
      </CardContent>
    </>
  )

  return (
    <Card
      data-status-tone={statusTone ?? 'neutral'}
      data-action-required={actionRequired ? 'true' : 'false'}
      sx={{
        height: '100%',
        minHeight: 120,
        borderRadius: 2,
        border: isPermissionDenied
          ? '1px dashed #EF4444'
          : actionHighlight
            ? `1px solid ${actionHighlight.borderColor}`
            : '1px solid',
        borderColor: isPermissionDenied || actionHighlight ? undefined : 'divider',
        boxShadow: 1,
        bgcolor: isPermissionDenied ? '#FFF5F5' : actionHighlight?.bgcolor,
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
