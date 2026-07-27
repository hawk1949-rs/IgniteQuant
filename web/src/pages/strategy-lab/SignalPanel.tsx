import { useMemo, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Flex,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import {
  PlusOutlined,
  SaveOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  COMPARE_OP_OPTIONS,
  SIGNAL_SIDE_META,
  createDefaultSignalConfig,
  createEmptyTerm,
  describeRule,
  listCompiledFactors,
  loadSignalConfig,
  persistSignalConfig,
  validateSignalConfig,
  type CompareOp,
  type ExtraConditions,
  type FormulaTerm,
  type SignalGeneratorConfig,
  type SignalRule,
  type SignalSide,
} from './signal-data'

const { Text, Paragraph } = Typography

function FormulaBuilder({
  rule,
  factors,
  onChange,
}: {
  rule: SignalRule
  factors: ReturnType<typeof listCompiledFactors>
  onChange: (next: SignalRule) => void
}) {
  const factorOptions = factors.map((f) => ({
    value: f.id,
    label: `${f.name}（${f.category}）`,
  }))

  const updateTerm = (id: string, partial: Partial<FormulaTerm>) => {
    onChange({
      ...rule,
      terms: rule.terms.map((t) => (t.id === id ? { ...t, ...partial } : t)),
    })
  }

  const addTerm = () => {
    const first = factors[0]
    onChange({
      ...rule,
      terms: [...rule.terms, createEmptyTerm(first)],
    })
  }

  const removeTerm = (id: string) => {
    onChange({
      ...rule,
      terms: rule.terms.filter((t) => t.id !== id),
    })
  }

  return (
    <Flex vertical gap={12}>
      <Flex wrap="wrap" gap={12} align="center" justify="space-between">
        <Space wrap>
          <Switch
            checked={rule.enabled}
            onChange={(v) => onChange({ ...rule, enabled: v })}
            checkedChildren="启用"
            unCheckedChildren="关"
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            条件组合
          </Text>
          <Select
            style={{ width: 120 }}
            value={rule.join}
            options={[
              { value: 'and', label: '全部满足 (AND)' },
              { value: 'or', label: '任一满足 (OR)' },
            ]}
            onChange={(v: 'and' | 'or') => onChange({ ...rule, join: v })}
          />
        </Space>
        <Button
          type="dashed"
          icon={<PlusOutlined />}
          onClick={addTerm}
          disabled={factors.length === 0}
        >
          添加条件
        </Button>
      </Flex>

      {factors.length === 0 && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          没有可用因子。请先到「因子与特征」启用并保存至少一个因子。
        </Text>
      )}

      {rule.terms.length === 0 ? (
        <Flex
          vertical
          align="center"
          justify="center"
          gap={10}
          style={{
            padding: '28px 16px',
            borderRadius: 12,
            border: '1px dashed rgba(180, 200, 230, 0.35)',
            background: '#121C30',
          }}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>
            从已编译因子中选题，组成信号公式。例如：趋势因子 &gt; 0 且 波动率因子 &lt; 1.2
          </Text>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={addTerm}
            disabled={factors.length === 0}
          >
            添加第一条条件
          </Button>
        </Flex>
      ) : (
        <Flex vertical gap={10}>
          {rule.terms.map((term, idx) => {
            const left = factors.find((f) => f.id === term.factorId)
            const leftKeys = left?.outputKeys ?? []
            const right = factors.find((f) => f.id === term.rhsFactorId)
            const rightKeys = right?.outputKeys ?? []
            return (
              <Card key={term.id} size="small" styles={{ body: { padding: 12 } }}>
                <Row gutter={[8, 8]} align="middle">
                  <Col flex="none">
                    <Tag>{idx === 0 ? '若' : rule.join === 'and' ? '且' : '或'}</Tag>
                  </Col>
                  <Col xs={24} sm={8} md={6}>
                    <Select
                      style={{ width: '100%' }}
                      placeholder="选择因子"
                      value={term.factorId || undefined}
                      options={factorOptions}
                      onChange={(factorId: string) => {
                        const f = factors.find((x) => x.id === factorId)
                        updateTerm(term.id, {
                          factorId,
                          outputKey: f?.outputKeys[0] ?? '',
                        })
                      }}
                    />
                  </Col>
                  <Col xs={12} sm={4} md={3}>
                    <Select
                      style={{ width: '100%' }}
                      value={term.outputKey || leftKeys[0]}
                      options={leftKeys.map((k) => ({ value: k, label: k }))}
                      disabled={leftKeys.length === 0}
                      onChange={(outputKey: string) => updateTerm(term.id, { outputKey })}
                    />
                  </Col>
                  <Col xs={12} sm={4} md={3}>
                    <Select
                      style={{ width: '100%' }}
                      value={term.op}
                      options={COMPARE_OP_OPTIONS.map((o) => ({
                        value: o.id,
                        label: o.label,
                      }))}
                      onChange={(op: CompareOp) => updateTerm(term.id, { op })}
                    />
                  </Col>
                  <Col xs={12} sm={4} md={3}>
                    <Select
                      style={{ width: '100%' }}
                      value={term.rhsType}
                      options={[
                        { value: 'number', label: '数值' },
                        { value: 'factor', label: '因子' },
                      ]}
                      onChange={(rhsType: 'number' | 'factor') =>
                        updateTerm(term.id, { rhsType })
                      }
                    />
                  </Col>
                  {term.rhsType === 'number' ? (
                    <Col xs={12} sm={6} md={5}>
                      <InputNumber
                        style={{ width: '100%' }}
                        value={term.rhsNumber}
                        onChange={(v) =>
                          updateTerm(term.id, { rhsNumber: Number(v ?? 0) })
                        }
                      />
                    </Col>
                  ) : (
                    <>
                      <Col xs={12} sm={6} md={4}>
                        <Select
                          style={{ width: '100%' }}
                          placeholder="比较因子"
                          value={term.rhsFactorId || undefined}
                          options={factorOptions}
                          onChange={(rhsFactorId: string) => {
                            const f = factors.find((x) => x.id === rhsFactorId)
                            updateTerm(term.id, {
                              rhsFactorId,
                              rhsOutputKey: f?.outputKeys[0] ?? '',
                            })
                          }}
                        />
                      </Col>
                      <Col xs={12} sm={4} md={3}>
                        <Select
                          style={{ width: '100%' }}
                          value={term.rhsOutputKey || rightKeys[0]}
                          options={rightKeys.map((k) => ({ value: k, label: k }))}
                          disabled={rightKeys.length === 0}
                          onChange={(rhsOutputKey: string) =>
                            updateTerm(term.id, { rhsOutputKey })
                          }
                        />
                      </Col>
                    </>
                  )}
                  <Col flex="none">
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => removeTerm(term.id)}
                    />
                  </Col>
                </Row>
              </Card>
            )
          })}
        </Flex>
      )}

      <Text type="secondary" style={{ fontSize: 12 }}>
        预览：{describeRule(rule, factors)}
      </Text>
    </Flex>
  )
}

export function SignalPanel() {
  const { message } = App.useApp()
  const [cfg, setCfg] = useState<SignalGeneratorConfig>(() => loadSignalConfig())
  const [activeSide, setActiveSide] = useState<SignalSide>('long')
  const [factorTick, setFactorTick] = useState(0)
  const compiled = useMemo(() => listCompiledFactors(), [factorTick])

  const errors = useMemo(
    () => validateSignalConfig(cfg, compiled),
    [cfg, compiled],
  )

  const patchRule = (side: SignalSide, next: SignalRule) => {
    setCfg((prev) => ({
      ...prev,
      rules: { ...prev.rules, [side]: next },
    }))
  }

  const patchExtras = (partial: Partial<ExtraConditions>) => {
    setCfg((prev) => ({
      ...prev,
      extras: { ...prev.extras, ...partial },
    }))
  }

  const onSave = () => {
    if (errors.length) {
      message.error(errors[0])
      return
    }
    persistSignalConfig(cfg)
    setCfg((prev) => ({ ...prev, updatedAt: new Date().toISOString() }))
    message.success('已保存信号发生器配置')
  }

  const onReset = () => {
    const next = createDefaultSignalConfig()
    setCfg(next)
    persistSignalConfig(next)
    setActiveSide('long')
    message.success('已重置信号配置')
  }

  const onRefreshFactors = () => {
    setFactorTick((n) => n + 1)
    message.success(`已刷新因子列表（${listCompiledFactors().length} 个启用）`)
  }

  return (
    <Flex vertical gap={12}>
      <Card size="small" styles={{ body: { padding: '10px 12px' } }}>
        <Paragraph type="secondary" style={{ marginBottom: 10, fontSize: 12, maxWidth: 720 }}>
          从已编译因子组成做多 / 做空 / 平仓公式，并可附加确认根数、TTL 等门禁；本页只定义规则契约。
        </Paragraph>
        <Row gutter={[10, 10]}>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              信号配置名称
            </Text>
            <Input
              size="small"
              value={cfg.name}
              onChange={(e) => setCfg((p) => ({ ...p, name: e.target.value }))}
              placeholder="例如：au_trend_breakout_v1"
            />
          </Col>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              可用因子（因子与特征 · 已启用）
            </Text>
            <Space wrap size={6}>
              <Button size="small" icon={<ReloadOutlined />} onClick={onRefreshFactors}>
                刷新因子
              </Button>
              <Tag color="blue">{compiled.length} 个</Tag>
              {compiled.slice(0, 6).map((f) => (
                <Tag key={f.id}>
                  {f.category} · {f.name}
                </Tag>
              ))}
              {compiled.length > 6 && <Tag>+{compiled.length - 6}</Tag>}
            </Space>
          </Col>
        </Row>
      </Card>

      <Card
        size="small"
        title="信号公式"
        extra={
          <Space wrap size={8}>
            <Button size="small" icon={<ReloadOutlined />} onClick={onReset}>
              重置
            </Button>
            <Button size="small" type="primary" icon={<SaveOutlined />} onClick={onSave}>
              保存信号
            </Button>
          </Space>
        }
      >
        {errors.length > 0 && (
          <Paragraph type="warning" style={{ fontSize: 12 }}>
            {errors.slice(0, 3).join('；')}
            {errors.length > 3 ? `…共 ${errors.length} 项` : ''}
          </Paragraph>
        )}

        <Tabs
          activeKey={activeSide}
          onChange={(k) => setActiveSide(k as SignalSide)}
          items={SIGNAL_SIDE_META.map((meta) => ({
            key: meta.id,
            label: (
              <span>
                <Tag color={meta.id === 'long' ? 'success' : meta.id === 'short' ? 'error' : 'warning'}>
                  {meta.label}
                </Tag>
                {!cfg.rules[meta.id].enabled && (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    关
                  </Text>
                )}
              </span>
            ),
            children: (
              <Flex vertical gap={12}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {meta.desc}
                </Text>
                <FormulaBuilder
                  rule={cfg.rules[meta.id]}
                  factors={compiled}
                  onChange={(next) => patchRule(meta.id, next)}
                />
              </Flex>
            ),
          }))}
        />
      </Card>

      <Card size="small" title="附加条件">
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          这些门禁作用于整套信号，不替代公式本身。
        </Paragraph>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              确认根数 confirmation_bars
            </Text>
            <InputNumber
              style={{ width: '100%' }}
              min={1}
              max={20}
              value={cfg.extras.confirmationBars}
              onChange={(v) => patchExtras({ confirmationBars: Number(v ?? 2) })}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              信号有效期 TTL（根）
            </Text>
            <InputNumber
              style={{ width: '100%' }}
              min={1}
              max={20}
              value={cfg.extras.signalTtlBars}
              onChange={(v) => patchExtras({ signalTtlBars: Number(v ?? 1) })}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              多空互斥
            </Text>
            <Flex align="center" style={{ height: 40 }}>
              <Switch
                checked={cfg.extras.longShortExclusive}
                onChange={(v) => patchExtras({ longShortExclusive: v })}
              />
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                同一根不可同时做多做空
              </Text>
            </Flex>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              平仓优先
            </Text>
            <Flex align="center" style={{ height: 40 }}>
              <Switch
                checked={cfg.extras.flatOverridesEntry}
                onChange={(v) => patchExtras({ flatOverridesEntry: v })}
              />
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                平仓与开仓冲突时先平
              </Text>
            </Flex>
          </Col>
          <Col span={24}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              备注（可选）
            </Text>
            <Input.TextArea
              rows={2}
              value={cfg.extras.note}
              placeholder="例如：仅趋势市启用；震荡市关闭开仓"
              onChange={(e) => patchExtras({ note: e.target.value })}
            />
          </Col>
        </Row>
      </Card>

      <Card size="small" title="规则摘要">
        <Row gutter={[10, 10]}>
          {SIGNAL_SIDE_META.map((meta) => (
            <Col key={meta.id} xs={24} md={8}>
              <Card size="small" styles={{ body: { padding: '10px 12px' } }}>
                <Tag
                  color={
                    meta.id === 'long' ? 'success' : meta.id === 'short' ? 'error' : 'warning'
                  }
                >
                  {meta.label}
                </Tag>
                <Text
                  type="secondary"
                  style={{ display: 'block', marginTop: 6, fontSize: 12, lineHeight: 1.45 }}
                >
                  {describeRule(cfg.rules[meta.id], compiled)}
                </Text>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
    </Flex>
  )
}
