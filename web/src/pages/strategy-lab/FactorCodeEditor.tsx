import { useEffect, useRef, useState } from 'react'
import Editor, { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'

// 不用 CDN：国内网络下默认 jsDelivr 常一直停在「加载编辑器…」
loader.config({ monaco })

type Props = {
  fileName: string
  value: string
  onChange: (next: string) => void
  height?: number
}

function PlainPythonEditor({
  fileName,
  value,
  onChange,
  height,
}: Props & { height: number }) {
  return (
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
  )
}

/** 因子模块在线 Python 编辑器（本地 Monaco；失败则降级为文本框）。 */
export function FactorCodeEditor({ fileName, value, onChange, height = 320 }: Props) {
  const [mode, setMode] = useState<'monaco' | 'plain'>('monaco')
  const [bootError, setBootError] = useState<string | null>(null)
  const readyRef = useRef(false)

  useEffect(() => {
    if (mode !== 'monaco') return
    readyRef.current = false
    const timer = window.setTimeout(() => {
      if (readyRef.current) return
      setBootError('Monaco 加载超时，已切换为纯文本编辑器')
      setMode('plain')
    }, 8000)
    return () => window.clearTimeout(timer)
  }, [mode])

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
        <span style={{ opacity: 0.75 }}>
          {mode === 'monaco'
            ? 'Python · Monaco（本地）'
            : 'Python · 纯文本（可继续编辑）'}
        </span>
      </div>
      {bootError && (
        <div style={{ padding: '6px 12px', fontSize: 11, color: '#FFD60A', background: '#1c1408' }}>
          {bootError}
        </div>
      )}
      {mode === 'plain' ? (
        <PlainPythonEditor
          fileName={fileName}
          value={value}
          onChange={onChange}
          height={height}
        />
      ) : (
        <Editor
          height={height}
          language="python"
          theme="vs-dark"
          path={fileName || 'untitled.py'}
          value={value}
          onChange={(v) => onChange(v ?? '')}
          onMount={() => {
            readyRef.current = true
            setBootError(null)
          }}
          loading={
            <div style={{ padding: 24, color: '#C8D0DC', fontSize: 12 }}>
              正在加载本地 Monaco…
            </div>
          }
          options={{
            fontSize: 13,
            fontFamily:
              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            tabSize: 4,
            automaticLayout: true,
            padding: { top: 12, bottom: 12 },
            renderLineHighlight: 'line',
            suggestOnTriggerCharacters: true,
          }}
        />
      )}
    </div>
  )
}
