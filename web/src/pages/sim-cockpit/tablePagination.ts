import { useCallback, useMemo, useState } from 'react'
import type { TablePaginationConfig } from 'antd'

const STORAGE_PREFIX = 'ignitequant.sim-cockpit.pageSize.'

export const SIM_TABLE_PAGE_SIZE_OPTIONS = ['5', '10', '20', '50'] as const

export function readStoredPageSize(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key)
    const n = raw ? Number(raw) : NaN
    if (Number.isFinite(n) && n > 0) return n
  } catch {
    // ignore storage failures
  }
  return fallback
}

export function writeStoredPageSize(key: string, size: number): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, String(size))
  } catch {
    // ignore storage failures
  }
}

/** Shared Ant Design pagination: size changer + total + compact controls. */
export function useSimTablePagination(
  storageKey: string,
  defaultPageSize = 10,
  totalItems = 0,
): TablePaginationConfig {
  const [pageSize, setPageSize] = useState(() =>
    typeof window === 'undefined'
      ? defaultPageSize
      : readStoredPageSize(storageKey, defaultPageSize),
  )
  const [current, setCurrent] = useState(1)

  const maxPage = Math.max(1, Math.ceil(totalItems / pageSize) || 1)
  const safeCurrent = Math.min(current, maxPage)

  const onChange = useCallback((page: number, size?: number) => {
    const nextSize = size && size !== pageSize ? size : pageSize
    const nextMax = Math.max(1, Math.ceil(totalItems / nextSize) || 1)
    setCurrent(Math.min(page, nextMax))
    if (size && size !== pageSize) {
      setPageSize(size)
      writeStoredPageSize(storageKey, size)
      setCurrent(1)
    }
  }, [pageSize, storageKey, totalItems])

  return useMemo(
    () => ({
      current: safeCurrent,
      pageSize,
      size: 'small' as const,
      showSizeChanger: true,
      showQuickJumper: true,
      pageSizeOptions: [...SIM_TABLE_PAGE_SIZE_OPTIONS],
      showTotal: (total, range) =>
        total > 0 ? `第 ${range[0]}-${range[1]} 条 / 共 ${total} 条` : '共 0 条',
      onChange,
      onShowSizeChange: (_page, size) => {
        setPageSize(size)
        writeStoredPageSize(storageKey, size)
        setCurrent(1)
      },
    }),
    [safeCurrent, pageSize, onChange, storageKey],
  )
}
