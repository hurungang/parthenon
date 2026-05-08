import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AppBar,
  Box,
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
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart'
import GatewayIcon from '@mui/icons-material/Router'
import ScheduleIcon from '@mui/icons-material/Schedule'
import HistoryIcon from '@mui/icons-material/History'
import FolderIcon from '@mui/icons-material/Folder'
import NotificationsIcon from '@mui/icons-material/Notifications'
import MonitorIcon from '@mui/icons-material/Monitor'
import LogoutIcon from '@mui/icons-material/Logout'
import SecurityIcon from '@mui/icons-material/Security'
import { useAuthStore } from '../stores/authStore'
import { PermissionErrorSnackbar } from '../components/permissions/PermissionErrorSnackbar'

const DRAWER_WIDTH = 240

interface NavItem {
  labelKey: string
  path: string
  icon: React.ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { labelKey: 'nav.dashboard', path: '/dashboard', icon: <DashboardIcon /> },
  { labelKey: 'nav.mcpHub', path: '/mcp', icon: <HubIcon /> },
  { labelKey: 'nav.skills', path: '/skills', icon: <BuildIcon /> },
  { labelKey: 'nav.sops', path: '/sops', icon: <AccountTreeIcon /> },
  { labelKey: 'nav.agents', path: '/agents', icon: <SmartToyIcon /> },
  { labelKey: 'nav.agentRoles', path: '/agents/roles', icon: <AssignmentIndIcon /> },
  { labelKey: 'nav.agentIdentities', path: '/agents/identities', icon: <BadgeIcon /> },
  { labelKey: 'nav.modelConfigs', path: '/agents/model-configs', icon: <TuneIcon /> },
  { labelKey: 'nav.agentInstances', path: '/agents/instances', icon: <MonitorHeartIcon /> },
  { labelKey: 'nav.gateway', path: '/gateway', icon: <GatewayIcon /> },
  { labelKey: 'nav.schedules', path: '/schedules', icon: <ScheduleIcon /> },
  { labelKey: 'nav.conversations', path: '/conversations', icon: <HistoryIcon /> },
  { labelKey: 'nav.results', path: '/results', icon: <FolderIcon /> },
  { labelKey: 'nav.notifications', path: '/notifications', icon: <NotificationsIcon /> },
  { labelKey: 'nav.observability', path: '/observability', icon: <MonitorIcon /> },
  { labelKey: 'nav.permissions', path: '/user-permissions', icon: <SecurityIcon /> },
]

/**
 * Top-level layout: navigation drawer, header, and outlet for page content.
 */
export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { claims, logout } = useAuthStore()
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleDrawerToggle = () => setMobileOpen(!mobileOpen)

  const drawerContent = (
    <Box>
      <Toolbar>
        <Typography variant="h6" noWrap component="div" fontWeight={700}>
          {t('app.title')}
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {NAV_ITEMS.map((item) => (
          <ListItem key={item.path} disablePadding>
            <ListItemButton
              selected={location.pathname === item.path}
              onClick={() => { navigate(item.path); setMobileOpen(false) }}
            >
              <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
              <ListItemText primary={t(item.labelKey)} />
            </ListItemButton>
          </ListItem>
        ))}
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
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH },
          }}
        >
          {drawerContent}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' },
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
