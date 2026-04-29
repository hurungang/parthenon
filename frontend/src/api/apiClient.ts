import axios, { AxiosError, type AxiosInstance } from 'axios'
import { API_CONFIG } from './API_CONFIG'
import { parsePermissionError, dispatchPermissionDeniedEvent } from '../utils/permissionError'

/**
 * Configured axios instance with auth header injection and error interceptors.
 * All frontend API calls should use this client.
 */
const apiClient: AxiosInstance = axios.create({
  baseURL: API_CONFIG.BASE_URL,
  timeout: API_CONFIG.TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: inject Authorization header from stored token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// Response interceptor: handle 401 by redirecting to login; 403 with
// structured permission data dispatches a targeted error event
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Clear stored tokens
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      // Redirect to login
      if (!window.location.pathname.includes('/login') && !window.location.pathname.includes('/callback')) {
        window.location.href = '/login'
      }
    } else if (error.response?.status === 403) {
      const permDetail = parsePermissionError(error)
      if (permDetail) {
        dispatchPermissionDeniedEvent(permDetail)
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
