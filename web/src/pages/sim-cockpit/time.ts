/** Format API ISO/UTC timestamps for cockpit UI in the browser's local timezone. */
export function formatLocalDateTime(value?: string | null): string {
  if (!value) return '—'
  const ms = Date.parse(value)
  if (Number.isNaN(ms)) {
    // Already a plain local-ish string; keep a compact slice.
    return value.length >= 19 ? value.slice(5, 19).replace('T', ' ') : value
  }
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
