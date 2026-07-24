import { Alert, Button, Slider, Space } from 'antd'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useSimCockpit } from './SimCockpitContext'
import { MiniCandleChart } from './MiniCandleChart'
import { actionLabel, qualityLabel, regimeLabel, riskActionLabel } from './labels'

export function ReplayPanel() {
  const { decisions, fills, bars, replayAt, setReplayAt, refresh, replay } = useSimCockpit()
  const [idx, setIdx] = useState(0)
  const focus = replay?.decision || decisions[0]

  const timeline = useMemo(() => {
    const stamps = new Set<string>()
    for (const d of decisions) if (d.created_at) stamps.add(d.created_at)
    for (const f of fills) if (f.created_at || f.trade_time) stamps.add(f.created_at || f.trade_time)
    return Array.from(stamps).sort()
  }, [decisions, fills])

  const enterReplay = (i: number) => {
    const at = timeline[i]
    if (!at) return
    setIdx(i)
    setReplayAt(at)
  }

  const exitReplay = () => {
    setReplayAt(null)
    void refresh()
  }

  return (
    <div className="flex flex-col gap-3">
      <section className="rounded-xl border border-line bg-panel/90 p-3.5">
        <h2 className="mb-2 text-[13px] font-semibold text-ink">复盘时间轴</h2>
        {timeline.length === 0 ? (
          <Alert type="info" showIcon banner message="暂无决策/成交时间点，无法复盘。" />
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              拖动滑块选择历史时刻；进入后总览数据切到该截面（暂停实时轮询）。
            </p>
            <Slider
              min={0}
              max={Math.max(timeline.length - 1, 0)}
              value={Math.min(idx, Math.max(timeline.length - 1, 0))}
              onChange={(v) => enterReplay(Number(v))}
              tooltip={{
                formatter: (v) => {
                  const t = timeline[Number(v ?? 0)]
                  return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : ''
                },
              }}
            />
            <Space className="mt-1" wrap>
              <Button type="primary" size="small" onClick={() => enterReplay(idx)} disabled={!timeline.length}>
                进入复盘
              </Button>
              <Button size="small" onClick={exitReplay} disabled={!replayAt}>
                退出复盘
              </Button>
              <span className="text-xs text-muted">
                {replayAt
                  ? `当前：${dayjs(replayAt).format('YYYY-MM-DD HH:mm:ss')}`
                  : '未进入复盘'}
              </span>
            </Space>
          </>
        )}
      </section>

      {replayAt ? (
        <div className="grid gap-3 xl:grid-cols-2">
          <section className="rounded-xl border border-line bg-panel/90 p-3.5">
            <h2 className="mb-2 text-[13px] font-semibold text-ink">该时刻决策</h2>
            {focus ? (
              <ul className="space-y-1.5 text-xs text-ink">
                <li>
                  <span className="text-faint">因子 </span>
                  {regimeLabel(focus.regime)} · {qualityLabel(focus.factor_quality)}
                </li>
                <li>
                  <span className="text-faint">信号 </span>
                  {focus.legacy_signal} · {JSON.stringify(focus.score_parts)}
                </li>
                <li>
                  <span className="text-faint">目标 </span>
                  {focus.target_before} → {focus.target_after} · {actionLabel(focus.applied_action)}
                </li>
                <li>
                  <span className="text-faint">风控 </span>
                  {focus.risk
                    ? `${riskActionLabel(focus.risk.action)} · 批准 ${focus.risk.approved_position}`
                    : '无事前风控记录'}
                </li>
              </ul>
            ) : (
              <p className="text-sm text-muted">该时刻无决策</p>
            )}
          </section>
          <section className="rounded-xl border border-line bg-panel/90 p-3.5">
            <h2 className="mb-2 text-[13px] font-semibold text-ink">截至该时刻 K 线</h2>
            {bars?.bars?.length ? (
              <MiniCandleChart bars={bars.bars} markers={bars.markers} height={220} />
            ) : (
              <p className="py-8 text-center text-sm text-muted">暂无 K 线</p>
            )}
          </section>
        </div>
      ) : (
        <Alert
          type="warning"
          showIcon
          banner
          message="选择时间点并进入复盘后，将显示该时刻决策与 K 线截面。日常观察请用「座舱总览」。"
        />
      )}
    </div>
  )
}
