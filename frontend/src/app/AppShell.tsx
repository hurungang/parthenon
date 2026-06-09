import { useEffect, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AppBar,
  Badge,
  Box,
  Collapse,
  CssBaseline,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Avatar,
  Tooltip,
} from '@mui/material'
import MenuIcon from '@mui/icons-material/Menu'
import DashboardIcon from '@mui/icons-material/Dashboard'
import HubIcon from '@mui/icons-material/Hub'
import BuildIcon from '@mui/icons-material/Build'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import AssignmentIndIcon from '@mui/icons-material/AssignmentInd'
import BadgeIcon from '@mui/icons-material/Badge'
import TuneIcon from '@mui/icons-material/Tune'
import ScheduleIcon from '@mui/icons-material/Schedule'
import MonitorIcon from '@mui/icons-material/Monitor'
import LogoutIcon from '@mui/icons-material/Logout'
import SecurityIcon from '@mui/icons-material/Security'
import SettingsIcon from '@mui/icons-material/Settings'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import TimelineIcon from '@mui/icons-material/Timeline'
import NotificationsIcon from '@mui/icons-material/Notifications'
import PanToolIcon from '@mui/icons-material/PanTool'
import { useAuthStore } from '../stores/authStore'
import { PermissionErrorSnackbar } from '../components/permissions/PermissionErrorSnackbar'
import apiClient from '../api/apiClient'
import type { InterveneMetrics } from '../types'

const DRAWER_WIDTH = 256

// Sidebar tokens — modern, minimal aesthetic.
const SIDEBAR_ACCENT = '#2563EB'
const SIDEBAR_ACTIVE_BG = 'rgba(0, 0, 0, 0.03)'
const SIDEBAR_HOVER_BG = 'rgba(0, 0, 0, 0.02)'
const SIDEBAR_FONT_SIZE = '15px'
const SIDEBAR_CHILD_FONT_SIZE = '13px'
const SIDEBAR_CHILD_ICON_SIZE = '16px'
const SIDEBAR_ICON_SIZE = '18px'
const SIDEBAR_ITEM_RADIUS = '8px'

/**
 * A single sidebar entry — either a top-level standalone item or a child of a {@link NavGroup}.
 * `labelKey` resolves through i18next (t(labelKey)); the resolved value is what the user sees.
 * `path` is the React Router 7 route the entry navigates to; it is also the value used to
 * detect the active route and to force-expand the parent group on a deep link.
 */
interface NavItem {
  labelKey: string
  path: string
  icon: React.ReactNode
}

/**
 * A collapsible sidebar group. `groupKey` is unique across the sidebar and is used as the
 * key in the component's `expandedGroups` state object. `labelKey` resolves to the group
 * header text. `children` are rendered in declaration order inside the `Collapse` body.
 */
interface NavGroup {
  groupKey: string
  labelKey: string
  icon: React.ReactNode
  children: NavItem[]
  lockedOpen?: boolean
}

/**
 * Standalone top-level entries that are not in any collapsible group. Currently just
 * the Dashboard entry — the new top-level layout has exactly one standalone item.
 */
const STANDALONE_ITEMS: NavItem[] = [
  { labelKey: 'nav.dashboard', path: '/dashboard', icon: <DashboardIcon /> },
]

/**
 * Declarative definition of the three sidebar groups. Conversation history, agent
 * executions, and results are consolidated under a single "Agent Trails" entry
 * (tabs inside the page). Notification sub-items (channels, groups, logs) are also
 * consolidated under a single "Notifications" entry. Gateway is hidden. The
 * Integrations group is locked open (cannot be collapsed).
 */
const NAV_GROUPS: NavGroup[] = [
  {
    groupKey: 'agents',
    labelKey: 'nav.groupAgents',
    icon: <SmartToyIcon />,
    children: [
      { labelKey: 'nav.agentRoles', path: '/agents/roles', icon: <AssignmentIndIcon /> },
      { labelKey: 'nav.agentIdentities', path: '/agents/identities', icon: <BadgeIcon /> },
      { labelKey: 'nav.agentTypes', path: '/agents', icon: <SmartToyIcon /> },
      { labelKey: 'nav.runtimeControl', path: '/agents/runtime-control', icon: <AccountTreeIcon /> },
      { labelKey: 'nav.skills', path: '/skills', icon: <BuildIcon /> },
      { labelKey: 'nav.sops', path: '/sops', icon: <AccountTreeIcon /> },
      { labelKey: 'nav.modelConfigs', path: '/agents/model-configs', icon: <TuneIcon /> },
      { labelKey: 'nav.schedules', path: '/schedules', icon: <ScheduleIcon /> },
      { labelKey: 'nav.agentTrails', path: '/agent-trails', icon: <TimelineIcon /> },
      { labelKey: 'nav.humanIntervene', path: '/agents/intervene', icon: <PanToolIcon /> },
    ],
  },
  {
    groupKey: 'integrations',
    labelKey: 'nav.groupIntegrations',
    icon: <HubIcon />,
    lockedOpen: true,
    children: [
      { labelKey: 'nav.mcpHub', path: '/mcp', icon: <HubIcon /> },
      { labelKey: 'nav.notifications', path: '/notifications', icon: <NotificationsIcon /> },
    ],
  },
  {
    groupKey: 'system',
    labelKey: 'nav.groupSystem',
    icon: <SettingsIcon />,
    children: [
      { labelKey: 'nav.observability', path: '/observability', icon: <MonitorIcon /> },
      { labelKey: 'nav.permissions', path: '/user-permissions', icon: <SecurityIcon /> },
      { labelKey: 'nav.systemConfig', path: '/system-config', icon: <SettingsIcon /> },
    ],
  },
]

/**
 * Default expansion state for the three groups on initial render. All groups start
 * expanded so operators can see the relocated items immediately after first load.
 */
const DEFAULT_EXPANDED_GROUPS: Record<string, boolean> = {
  agents: true,
  integrations: true,
  system: true,
}

// Shared sx for standalone and child items — subtle grey active state with 8px radius.
const itemButtonSx = {
  fontSize: SIDEBAR_FONT_SIZE,
  whiteSpace: 'nowrap',
  mx: '4px',
  borderRadius: SIDEBAR_ITEM_RADIUS,
  '&:hover': { backgroundColor: SIDEBAR_HOVER_BG },
  '&.Mui-selected': {
    backgroundColor: SIDEBAR_ACTIVE_BG,
    fontWeight: 500,
    '&:hover': { backgroundColor: SIDEBAR_ACTIVE_BG },
  },
} as const

// Child items — indented, smaller, grey text to visually subordinate under the group header.
const childItemButtonSx = {
  ...itemButtonSx,
  pl: 4,
  py: '3px',
  fontSize: SIDEBAR_CHILD_FONT_SIZE,
  color: 'text.secondary',
} as const

// Group header — text-only hover/active (no background), matches the MUI Dashboard template.
const groupHeaderSx = {
  fontSize: SIDEBAR_FONT_SIZE,
  mx: '4px',
  borderRadius: SIDEBAR_ITEM_RADIUS,
  '&:hover': { color: SIDEBAR_ACCENT, backgroundColor: 'transparent' },
  '&.Mui-selected': {
    backgroundColor: 'transparent',
    color: SIDEBAR_ACCENT,
    fontWeight: 500,
    '& .MuiListItemText-primary': { color: SIDEBAR_ACCENT },
    '&:hover': { color: SIDEBAR_ACCENT, backgroundColor: 'transparent' },
  },
} as const

// Icon slot — 14px icon in a compact flex slot.
const iconSx = { minWidth: 28,  color: 'inherit',
  '& .MuiSvgIcon-root': { fontSize: SIDEBAR_ICON_SIZE }, } as const

// Child icon slot — smaller than parent group to reinforce visual hierarchy.
const childIconSx = {
  minWidth: 20,
  mr: '6px',
  color: 'inherit',
  '& .MuiSvgIcon-root': { fontSize: SIDEBAR_CHILD_ICON_SIZE },
} as const

// Group label typography — clean modern style, normal case.
const groupLabelTypographyProps = {
  fontSize: SIDEBAR_FONT_SIZE,
  fontWeight: 600,
  color: 'text.secondary',
}

/**
 * Top-level layout: navigation drawer, header, and outlet for page content.
 */
export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { claims, logout } = useAuthStore()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [expandedGroups, setExpandedGroups] =
    useState<Record<string, boolean>>(DEFAULT_EXPANDED_GROUPS)
  const [interveneMetrics, setInterveneMetrics] = useState<InterveneMetrics | null>(null)

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const { data } = await apiClient.get<InterveneMetrics>('/intervene/metrics')
        setInterveneMetrics(data)
      } catch {
        // Metrics are best-effort
      }
    }
    void fetchMetrics()
    const interval = setInterval(fetchMetrics, 15_000)
    return () => clearInterval(interval)
  }, [])

  const handleDrawerToggle = () => setMobileOpen(!mobileOpen)

  const toggleGroup = (groupKey: string) => {
    const group = NAV_GROUPS.find((g) => g.groupKey === groupKey)
    if (group?.lockedOpen) return
    setExpandedGroups((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }))
  }

  const drawerContent = (
    <Box>
      <Toolbar>
        <Typography variant="h6" noWrap component="div" fontWeight={700}>
          {t('app.title')}
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {/* Standalone top-level items (Dashboard) — flat, above any group. */}
        {STANDALONE_ITEMS.map((item) => (
          <ListItem key={item.path} disablePadding>
            <ListItemButton
              selected={location.pathname === item.path}
              onClick={() => { navigate(item.path); setMobileOpen(false) }}
              sx={itemButtonSx}
            >
              <ListItemIcon sx={iconSx}>{item.icon}</ListItemIcon>
              <ListItemText
                primary={t(item.labelKey)}
                primaryTypographyProps={{ fontSize: SIDEBAR_FONT_SIZE }}
              />
            </ListItemButton>
          </ListItem>
        ))}

        {/* Sidebar groups (Agents, Integrations, System). Single data-driven render. */}
        {NAV_GROUPS.map((group) => {
          // A group is "active" when any of its children matches the current pathname.
          // Active state propagates to the header (visually indicated) and force-expands
          // the body, regardless of the user's prior collapsed preference — supports
          // deep-link / direct-URL navigation per PRD AC #14 and test plan §4.1.
          const isGroupActive = group.children.some(
            (child) => child.path === location.pathname,
          )
          const isExpanded = expandedGroups[group.groupKey] ?? true
          const showChildren = isExpanded || isGroupActive

          return (
            <Box key={group.groupKey}>
              <ListItem disablePadding>
                <ListItemButton
                  selected={isGroupActive}
                  onClick={() => toggleGroup(group.groupKey)}
                  sx={groupHeaderSx}
                  aria-expanded={showChildren}
                >
                  <ListItemIcon sx={iconSx}>{group.icon}</ListItemIcon>
                  <ListItemText
                    primary={t(group.labelKey)}
                    primaryTypographyProps={groupLabelTypographyProps}
                  />
                  {!group.lockedOpen && (
                    isExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />
                  )}
                </ListItemButton>
              </ListItem>
              <Collapse in={showChildren} timeout="auto" unmountOnExit>
                <List component="div" disablePadding>
                  {group.children.map((child) => (
                    <ListItem key={child.path} disablePadding>
                      <ListItemButton
                        selected={location.pathname === child.path}
                        onClick={() => { navigate(child.path); setMobileOpen(false) }}
                        sx={childItemButtonSx}
                      >
                        <ListItemIcon sx={childIconSx}>
                          {child.path === '/agents/intervene' && (interveneMetrics?.pending_count ?? 0) > 0 ? (
                            <Badge badgeContent={interveneMetrics!.pending_count} color="error" overlap="circular">
                              {child.icon}
                            </Badge>
                          ) : (
                            child.icon
                          )}
                        </ListItemIcon>
                        <ListItemText
                          primary={t(child.labelKey)}
                          primaryTypographyProps={{
                            fontSize: SIDEBAR_CHILD_FONT_SIZE,
                            color: 'text.secondary',
                          }}
                        />
                      </ListItemButton>
                    </ListItem>
                  ))}
                </List>
              </Collapse>
            </Box>
          )
        })}
      </List>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', height: '100vh' }}>
      <CssBaseline />

      {/* App Bar */}
      <AppBar
        position="fixed"
        sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
        elevation={1}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>
            {t('app.title')}
          </Typography>
          <Tooltip title={claims?.email ?? claims?.sub ?? ''}>
            <Avatar sx={{ width: 32, height: 32, mr: 1, fontSize: 14 }}>
              {(claims?.name ?? claims?.preferred_username ?? 'U')[0].toUpperCase()}
            </Avatar>
          </Tooltip>
          <Tooltip title={t('nav.logout')}>
            <IconButton color="inherit" onClick={logout} size="small">
              <LogoutIcon />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      {/* Sidebar drawer (permanent on desktop, temporary on mobile) */}
      <Box
        component="nav"
        sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, scrollbarGutter: 'stable' },
          }}
        >
          {drawerContent}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box', scrollbarGutter: 'stable' },
          }}
          open
        >
          {drawerContent}
        </Drawer>
      </Box>

      {/* Page content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          mt: '64px',
          overflow: 'auto',
        }}
      >
        <Outlet />
      </Box>
      <PermissionErrorSnackbar />
    </Box>
  )
}
