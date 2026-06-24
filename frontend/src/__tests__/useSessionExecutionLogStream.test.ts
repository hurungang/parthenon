import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useSessionExecutionLogStream } from '../hooks/useSessionExecutionLogStream'

function buildNdjsonStream(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const line of lines) {
        controller.enqueue(encoder.encode(`${line}\n`))
      }
      controller.close()
    },
  })
}

describe('useSessionExecutionLogStream', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('access_token', 'test-token')
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('streams NDJSON log entries and transitions to idle on terminal marker', async () => {
    const sessionId = 'sess-stream-1'
    fetchMock.mockResolvedValueOnce({
      ok: true,
      body: buildNdjsonStream([
        JSON.stringify({
          type: 'log_entry',
          entry: {
            id: 'entry-1',
            timestamp: '2026-05-29T10:00:00Z',
            event_type: 'system',
            log_level: 'INFO',
            message: 'runtime started',
            data: {},
          },
        }),
        JSON.stringify({
          type: 'stream_completed',
          session_id: sessionId,
          session_status: 'completed',
        }),
      ]),
      status: 200,
    } as Response)

    const { result } = renderHook(() =>
      useSessionExecutionLogStream({
        sessionId,
        enabled: true,
      }),
    )

    await waitFor(() => {
      expect(result.current.entries).toHaveLength(1)
      expect(result.current.entries[0]?.id).toBe('entry-1')
    })

    await waitFor(() => {
      expect(result.current.connectionState).toBe('idle')
      expect(result.current.isFallback).toBe(false)
    })
  })

  it('falls back after stream request failure when retries are exhausted', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, body: null } as Response)

    const { result } = renderHook(() =>
      useSessionExecutionLogStream({
        sessionId: 'sess-stream-2',
        enabled: true,
        reconnectAttempts: 0,
      }),
    )

    await waitFor(() => {
      expect(result.current.connectionState).toBe('fallback')
      expect(result.current.isFallback).toBe(true)
    })
  })
})
