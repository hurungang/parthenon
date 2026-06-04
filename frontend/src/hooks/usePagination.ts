import { useState, useCallback, useMemo } from 'react'

interface UsePaginationOptions {
  initialPage?: number
  initialRowsPerPage?: number
  rowsPerPageOptions?: number[]
}

export interface PaginationState {
  page: number
  rowsPerPage: number
  offset: number
  limit: number
}

export function usePagination(options: UsePaginationOptions = {}) {
  const {
    initialPage = 0,
    initialRowsPerPage = 25,
    rowsPerPageOptions = [10, 25, 50, 100],
  } = options

  const [page, setPage] = useState(initialPage)
  const [rowsPerPage, setRowsPerPage] = useState(initialRowsPerPage)

  const onPageChange = useCallback((_: unknown, newPage: number) => {
    setPage(newPage)
  }, [])

  const onRowsPerPageChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10))
    setPage(0)
  }, [])

  const resetPage = useCallback(() => {
    setPage(0)
  }, [])

  const offset = useMemo(() => page * rowsPerPage, [page, rowsPerPage])
  const limit = rowsPerPage

  return {
    page,
    rowsPerPage,
    offset,
    limit,
    onPageChange,
    onRowsPerPageChange,
    resetPage,
    rowsPerPageOptions,
  }
}
