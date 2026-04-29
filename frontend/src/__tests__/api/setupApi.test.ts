import { describe, it, expect, vi, afterEach } from 'vitest'
import { getIdentityStatus, postSetupIdentity } from '../../api/setupApi'
import { SetupState, ProviderType } from '../../types/setup'
import type { IdentityStatusResponse, ProviderSetupRequest, ProviderSetupResult } from '../../types/setup'

vi.mock('../../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

// Import the mocked module AFTER vi.mock so we get the mock instance
import apiClient from '../../api/apiClient'
const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)

describe('setupApi', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('getIdentityStatus returns IdentityStatusResponse on 200', async () => {
    const resp: IdentityStatusResponse = {
      setup_state: SetupState.NOT_CONFIGURED,
      provider_type: null,
      oidc_provider_url: null,
    }
    mockedGet.mockResolvedValueOnce({ data: resp })
    const result = await getIdentityStatus()
    expect(result).toEqual(resp)
    expect(mockedGet).toHaveBeenCalledWith('/setup/identity-status')
  })

  it('getIdentityStatus propagates on network error', async () => {
    const error = new Error('network fail')
    mockedGet.mockRejectedValueOnce(error)
    await expect(getIdentityStatus()).rejects.toThrow('network fail')
  })

  it('postSetupIdentity returns ProviderSetupResult on 200', async () => {
    const req: ProviderSetupRequest = { provider_type: ProviderType.KEYCLOAK_BUNDLED }
    const resp: ProviderSetupResult = {
      success: true,
      provider_type: ProviderType.KEYCLOAK_BUNDLED,
      oidc_provider_url: 'http://localhost:8080/realms/parthenon',
      realm_name: 'parthenon',
      client_id: 'parthenon',
      error_code: null,
      detail: null,
    }
    mockedPost.mockResolvedValueOnce({ data: resp })
    const result = await postSetupIdentity(req)
    expect(result).toEqual(resp)
    expect(mockedPost).toHaveBeenCalledWith('/setup/identity', req)
  })

  it('postSetupIdentity throws on 502 Keycloak error', async () => {
    const error = { isAxiosError: true, response: { status: 502 } }
    mockedPost.mockRejectedValueOnce(error)
    await expect(postSetupIdentity({ provider_type: ProviderType.KEYCLOAK_BUNDLED })).rejects.toBe(error)
  })

  it('postSetupIdentity throws on 409 already-configured', async () => {
    const error = { isAxiosError: true, response: { status: 409 } }
    mockedPost.mockRejectedValueOnce(error)
    await expect(postSetupIdentity({ provider_type: ProviderType.KEYCLOAK_BUNDLED })).rejects.toBe(error)
  })
})
