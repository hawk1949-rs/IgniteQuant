type Props = {
  title: string
  english: string
  summary: string
}

/** 分区占位页，风格对齐模拟盘座舱 Section。 */
export function ComingSoonPanel({ title, english, summary }: Props) {
  return (
    <section className="rounded-xl border border-line bg-panel/90">
      <div className="flex items-center justify-between gap-3 border-b border-line/70 px-3.5 py-2">
        <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
        <span className="text-[11px] uppercase tracking-wide text-faint">{english}</span>
      </div>
      <div className="space-y-2 p-3.5">
        <p className="max-w-xl text-sm text-muted">{summary}</p>
        <p className="text-[11px] text-faint">模块骨架已就绪，功能将在后续迭代接入。</p>
      </div>
    </section>
  )
}
