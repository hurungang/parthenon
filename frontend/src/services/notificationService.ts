/**
 * Typed API client for all notification REST endpoints.
 * Uses the shared apiClient (axios) with JWT bearer token injection.
 */
import apiClient from '../api/apiClient'
import type {
  ChannelPropertyWrite,
  NotificationChannel,
  NotificationLog,
  RecipientGroup,
} from '../types'

// ── Request types ──────────────────────────────────────────────────────────────

export interface CreateChannelRequest {
  name: string
  channel_type: string
  description?: string | null
  properties: ChannelPropertyWrite[]
}

export interface UpdateChannelRequest {
  name?: string
  description?: string | null
  is_active?: boolean
  properties?: ChannelPropertyWrite[]
}

export interface CreateRecipientGroupRequest {
  name: string
  slug?: string
  description?: string | null
  is_active?: boolean
}

export interface UpdateRecipientGroupRequest {
  name?: string
  slug?: string
  description?: string | null
  is_active?: boolean
}

export interface ListLogsParams {
  group_id?: string
  channel_id?: string
  log_status?: string
  limit?: number
  offset?: number
}

export interface TestChannelResponse {
  success: boolean
  error?: string | null
}

export interface SendNotificationRequest {
  group_slug: string
  subject?: string | null
  body: string
  source_type?: string
  source_id?: string | null
}

export interface SendNotificationResponse {
  notification_log_ids: string[]
}

// ── Notification channels ──────────────────────────────────────────────────────

export async function listChannels(params?: { limit?: number; offset?: number }): Promise<NotificationChannel[]> {
  const { data } = await apiClient.get<NotificationChannel[]>('/notifications/channels', { params })
  return data
}

export async function createChannel(req: CreateChannelRequest): Promise<NotificationChannel> {
  const { data } = await apiClient.post<NotificationChannel>('/notifications/channels', req)
  return data
}

export async function getChannel(id: string): Promise<NotificationChannel> {
  const { data } = await apiClient.get<NotificationChannel>(`/notifications/channels/${id}`)
  return data
}

export async function updateChannel(
  id: string,
  req: UpdateChannelRequest,
): Promise<NotificationChannel> {
  const { data } = await apiClient.put<NotificationChannel>(
    `/notifications/channels/${id}`,
    req,
  )
  return data
}

export async function deleteChannel(id: string): Promise<void> {
  await apiClient.delete(`/notifications/channels/${id}`)
}

export async function testChannel(
  id: string,
  testRecipient: string,
): Promise<TestChannelResponse> {
  const { data } = await apiClient.post<TestChannelResponse>(
    `/notifications/channels/${id}/test`,
    { test_recipient: testRecipient },
  )
  return data
}

// ── Recipient groups ───────────────────────────────────────────────────────────

export async function listRecipientGroups(params?: { limit?: number; offset?: number }): Promise<RecipientGroup[]> {
  const { data } = await apiClient.get<RecipientGroup[]>('/notifications/recipient-groups', { params })
  return data
}

export async function createRecipientGroup(
  req: CreateRecipientGroupRequest,
): Promise<RecipientGroup> {
  const { data } = await apiClient.post<RecipientGroup>('/notifications/recipient-groups', req)
  return data
}

export async function getRecipientGroup(id: string): Promise<RecipientGroup> {
  const { data } = await apiClient.get<RecipientGroup>(`/notifications/recipient-groups/${id}`)
  return data
}

export async function updateRecipientGroup(
  id: string,
  req: UpdateRecipientGroupRequest,
): Promise<RecipientGroup> {
  const { data } = await apiClient.put<RecipientGroup>(
    `/notifications/recipient-groups/${id}`,
    req,
  )
  return data
}

export async function deleteRecipientGroup(id: string): Promise<void> {
  await apiClient.delete(`/notifications/recipient-groups/${id}`)
}

export async function assignChannelToGroup(
  groupId: string,
  channelId: string,
  recipientProperties?: Record<string, unknown>,
): Promise<void> {
  await apiClient.post(`/notifications/recipient-groups/${groupId}/channels`, {
    channel_id: channelId,
    recipient_properties: recipientProperties,
  })
}

export async function removeChannelFromGroup(
  groupId: string,
  channelId: string,
): Promise<void> {
  await apiClient.delete(
    `/notifications/recipient-groups/${groupId}/channels/${channelId}`,
  )
}

// ── Manual send ────────────────────────────────────────────────────────────────

export async function sendNotification(
  req: SendNotificationRequest,
): Promise<SendNotificationResponse> {
  const { data } = await apiClient.post<SendNotificationResponse>(
    '/notifications/send',
    req,
  )
  return data
}

// ── Delivery logs ──────────────────────────────────────────────────────────────

export async function listNotificationLogs(
  params?: ListLogsParams,
): Promise<NotificationLog[]> {
  const { data } = await apiClient.get<NotificationLog[]>('/notifications/logs', { params })
  return data
}

export async function getNotificationLog(id: string): Promise<NotificationLog> {
  const { data } = await apiClient.get<NotificationLog>(`/notifications/logs/${id}`)
  return data
}
