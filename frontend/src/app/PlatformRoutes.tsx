/**
 * Platform console sub-routes (/platform/*), nested inside the
 * PlatformAdminRoute guard.  These routes do not exist when multi-tenancy
 * is off (the guard redirects).
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import { TenantManagementPage } from '../pages/platform/TenantManagementPage'
import { PlatformSettingsPage } from '../pages/platform/PlatformSettingsPage'
import { PlatformAuditPage } from '../pages/platform/PlatformAuditPage'

export function PlatformRoutes() {
  return (
    <Routes>
      <Route index element={<Navigate to="tenants" replace />} />
      <Route path="tenants" element={<TenantManagementPage />} />
      <Route path="settings" element={<PlatformSettingsPage />} />
      <Route path="audit" element={<PlatformAuditPage />} />
      <Route path="*" element={<Navigate to="tenants" replace />} />
    </Routes>
  )
}
