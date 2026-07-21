type Props = {
  fileName: string
  value: string
  onChange: (next: string) => void
  height?: number
}

/**
 * 因子模块 Python 编辑器。
 * 不使用 Monaco：本地 monaco-editor 体积过大，进入因子页会长时间卡住甚至假死。
 */
export function FactorCodeEditor({ fileName, value, onChange, height = 320 }: Props) {
  return (
    <div
      style={{
        borderRadius: 12,
        overflow: 'hidden',
        border: '1px solid rgba(180, 200, 230, 0.28)',
        background: '#0d1117',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          padding: '6px 12px',
          background: '#161b22',
          borderBottom: '1px solid rgba(180, 200, 230, 0.18)',
          fontSize: 12,
          color: '#C8D0DC',
        }}
      >
        <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' }}>
          {fileName || 'untitled.py'}
        </span>
        <span style={{ opacity: 0.75 }}>Python</span>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        aria-label={fileName || 'python source'}
        style={{
          display: 'block',
          width: '100%',
          height,
          margin: 0,
          padding: '12px 14px',
          border: 'none',
          outline: 'none',
          resize: 'vertical',
          background: '#0d1117',
          color: '#e6edf3',
          fontSize: 13,
          lineHeight: 1.55,
          fontFamily:
            "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace",
          tabSize: 4,
          boxSizing: 'border-box',
        }}
      />
    </div>
  )
}
