/**
 * usePlatformAccess — sidebar/route gating by REAL permission evaluation.
 *
 * Phase 11 (task 11.5): the platform menu group must render ONLY when the
 * signed-in session's permission evaluation grants `platform::settings`
 * read — NOT merely when multi-tenancy is enabled.  This fixes the
 * user-reported bug where a customer-tenant admin (e.g. acme) saw the
 * platform items whenever the tenancy switch was on.
 *
 * The probe is a cheap authenticated backend read of the platform
 * settings endpoint (guarded by `platform::settings` read); 200 = the
 * session's role space contains the grant, 403 = denied.  The query key
 * is SHARED with PlatformAdminRoute so the sidebar and the route guard
 * hit the same cache entry (one probe per session).
 */
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useAuthStore } from '../stores/authStore'
import { getPlatformSettings } from '../api/platformAdminApi'

export type PlatformAccess = 'pending' | 'allowed' | 'denied'

export function usePlatformAccess(): PlatformAccess {
  const { isAuthenticated, isSuperAdmin, multiTenancyEnabled } = useAuthStore()

  // The super-admin break-glass account is the bootstrap platform
  // administrator — no probe needed.
  const probe = useQuery({
    queryKey: ['platform', 'access-probe'],
    enabled: isAuthenticated && multiTenancyEnabled === true && !isSuperAdmin,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      try {
        return await getPlatformSettings()
      } catch (err) {
        if (isAxiosError(err) && err.response?.status === 403) {
          return 'denied'
        }
        throw err
      }
    },
  })

  if (!isAuthenticated || multiTenancyEnabled !== true) return 'denied'
  if (isSuperAdmin) return 'allowed'
  if (probe.isLoading || probe.isPending) return 'pending'
  return probe.data === 'denied' ? 'denied' : 'allowed'
}
