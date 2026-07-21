import { useEffect, useMemo, useState } from 'react'
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
  CopyOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons'
import { FactorCodeEditor } from './FactorCodeEditor'
import {
  BOUNDARY_RULES,
  FACTOR_MODULE_CONTRACT,
  RAW_FIELDS,
  TIMEFRAME_OPTIONS,
  buildFeatureDictPreview,
  collectOutputKeys,
  createDefaultMiningConfig,
  createEmptyModule,
  deleteFactorCombo,
  loadFactorMiningConfig,
  loadSavedFactorCombos,
  modulePathFromFileName,
  persistFactorMiningConfig,
  sanitizePyFileName,
  saveFactorComboAsNew,
  summarizeFactorCombo,
  updateFactorCombo,
  validateModules,
  type FactorMiningConfig,
  type FactorModule,
  type SavedFactorCombo,
  type TimeframeId,
} from './factor-data'

const { Text, Paragraph, Title } = Typography

function ModuleEditor({
  mod,
  onChange,
}: {
  mod: FactorModule
  onChange: (partial: Partial<FactorModule>) => void
}) {
  const renameFactor = (name: string) => {
    // 中文显示名不强制改写 .py 文件名；仅 ASCII 命名时同步 fileName
    const stem = name.trim()
    if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(stem)) {
      const fileName = sanitizePyFileName(stem)
      onChange({
        name,
        fileName,
        modulePath: modulePathFromFileName(fileName),
      })
      return
    }
    onChange({ name })
  }

  return (
    <Flex vertical gap={12}>
      <Row gutter={[12, 12]} align="middle">
        <Col flex="none">
          <Switch
            checked={mod.enabled}
            onChange={(v) => onChange({ enabled: v })}
            checkedChildren="启用"
            unCheckedChildren="关"
          />
        </Col>
        <Col xs={24} sm={10} md={8}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            因子命名
          </Text>
          <Input
            value={mod.name}
            placeholder="例如：波动率过滤"
            onChange={(e) => renameFactor(e.target.value)}
          />
        </Col>
        <Col xs={24} sm={12} md={10}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            触发 K 线周期
          </Text>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            value={mod.requiredTimeframes}
            placeholder="选择已闭合周期"
            options={TIMEFRAME_OPTIONS.map((t) => ({ value: t.id, label: t.label }))}
            onChange={(v: TimeframeId[]) => onChange({ requiredTimeframes: v })}
          />
        </Col>
        <Col span={24}>
          <FactorCodeEditor
            fileName={mod.fileName}
            value={mod.source}
            onChange={(source) => onChange({ source })}
          />
        </Col>
      </Row>
    </Flex>
  )
}

export function FactorPanel() {
  const { message, modal } = App.useApp()
  const [cfg, setCfg] = useState<FactorMiningConfig>(() => loadFactorMiningConfig())
  const [combos, setCombos] = useState<SavedFactorCombo[]>(() => loadSavedFactorCombos())
  const [selectedComboId, setSelectedComboId] = useState<string>()
  const [comboName, setComboName] = useState('')
  const [comboNote, setComboNote] = useState('')
  const [activeModuleId, setActiveModuleId] = useState<string>(
    () => loadFactorMiningConfig().modules[0]?.id ?? '',
  )

  useEffect(() => {
    if (cfg.modules.length === 0) {
      setActiveModuleId('')
      return
    }
    if (!cfg.modules.some((m) => m.id === activeModuleId)) {
      setActiveModuleId(cfg.modules[0].id)
    }
  }, [cfg.modules, activeModuleId])

  const activeModule = cfg.modules.find((m) => m.id === activeModuleId)

  const errors = useMemo(() => validateModules(cfg.modules), [cfg.modules])
  const saveErrors = useMemo(
    () => validateModules(cfg.modules, { lintSource: true }),
    [cfg.modules],
  )
  const keys = useMemo(() => collectOutputKeys(cfg.modules), [cfg.modules])
  const preview = useMemo(() => buildFeatureDictPreview(cfg), [cfg])

  const patchPipeline = (partial: Partial<FactorMiningConfig['pipeline']>) => {
    setCfg((prev) => ({
      ...prev,
      pipeline: {
        ...prev.pipeline,
        ...partial,
        closedBarsOnly: true,
        rawFields: prev.pipeline.rawFields,
      },
    }))
  }

  const updateModule = (id: string, partial: Partial<FactorModule>) => {
    setCfg((prev) => ({
      ...prev,
      modules: prev.modules.map((m) => (m.id === id ? { ...m, ...partial } : m)),
    }))
  }

  const syncDraft = (next: FactorMiningConfig) => {
    setCfg(next)
    persistFactorMiningConfig(next)
  }

  const onLoadCombo = (id: string | undefined) => {
    setSelectedComboId(id)
    if (!id) return
    const hit = combos.find((c) => c.id === id)
    if (!hit) {
      message.error('组合不存在')
      return
    }
    syncDraft(hit.config)
    setComboName(hit.name)
    setComboNote(hit.note)
    setActiveModuleId(hit.config.modules[0]?.id ?? '')
    message.success(`已载入因子组合「${hit.name}」`)
  }

  const onSaveDraft = () => {
    if (errors.length) {
      message.error(errors[0])
      return
    }
    persistFactorMiningConfig(cfg)
    message.success('草稿已保存（仅本机编辑缓存，不会出现在回测看板）')
  }

  const onSaveAsNewCombo = () => {
    if (saveErrors.length) {
      message.error(saveErrors[0])
      return
    }
    const name = comboName.trim() || cfg.workspaceName.trim()
    if (!name) {
      message.error('请先填写因子组合名称')
      return
    }
    const { list, combo } = saveFactorComboAsNew(name, comboNote, cfg)
    setCombos(list)
    setSelectedComboId(combo.id)
    setComboName(combo.name)
    persistFactorMiningConfig({ ...cfg, workspaceName: combo.name })
    setCfg((p) => ({ ...p, workspaceName: combo.name }))
    message.success(`已保存因子组合「${combo.name}」，可在回测看板节点 1 选用`)
  }

  const onUpdateCombo = () => {
    if (!selectedComboId) {
      message.warning('请先从下拉框选中要覆盖的组合，或改用「另存为」')
      return
    }
    if (saveErrors.length) {
      message.error(saveErrors[0])
      return
    }
    const name = comboName.trim() || cfg.workspaceName.trim()
    if (!name) {
      message.error('请先填写因子组合名称')
      return
    }
    const result = updateFactorCombo(selectedComboId, name, comboNote, cfg)
    if (!result) {
      message.error('组合不存在，请另存为新组合')
      return
    }
    setCombos(result.list)
    setComboName(result.combo.name)
    persistFactorMiningConfig({ ...cfg, workspaceName: result.combo.name })
    setCfg((p) => ({ ...p, workspaceName: result.combo.name }))
    message.success(`已更新因子组合「${result.combo.name}」`)
  }

  const onDeleteCombo = () => {
    if (!selectedComboId) {
      message.warning('请先选中要删除的组合')
      return
    }
    const hit = combos.find((c) => c.id === selectedComboId)
    modal.confirm({
      title: `删除因子组合「${hit?.name ?? selectedComboId}」？`,
      content: '回测看板中已引用该组合的装配将无法解析描述（需重新选择）。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => {
        const next = deleteFactorCombo(selectedComboId)
        setCombos(next)
        setSelectedComboId(undefined)
        message.success('已删除')
      },
    })
  }

  const onReset = () => {
    const next = createDefaultMiningConfig()
    syncDraft(next)
    setSelectedComboId(undefined)
    setComboName('')
    setComboNote('')
    setActiveModuleId(next.modules[0]?.id ?? '')
    message.success('已重置为空白示范草稿')
  }

  const onAddModule = () => {
    const next = createEmptyModule()
    setCfg((prev) => ({ ...prev, modules: [...prev.modules, next] }))
    setActiveModuleId(next.id)
  }

  const onCopyContract = async () => {
    try {
      await navigator.clipboard.writeText(FACTOR_MODULE_CONTRACT)
      message.success('已复制 FactorModule 契约到剪贴板')
    } catch {
      message.warning('复制失败，请手动选中下方代码')
    }
  }

  return (
    <Flex vertical gap={16}>
      <Card>
        <Text
          style={{
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: '#0A84FF',
          }}
        >
          Factor Mining
        </Text>
        <Title level={3} style={{ marginTop: 8, marginBottom: 8, color: '#F5F5F7' }}>
          因子与特征
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 680 }}>
          编辑模块与管道后，用下方「命名保存」写入因子组合库；回测看板装配区节点 1 只从该库选用。
        </Paragraph>
      </Card>

      <Card
        title="因子组合库（供回测看板）"
        extra={<Tag color="blue">{combos.length} 个已保存</Tag>}
      >
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 16 }}>
          给当前模块组合起名并入库后，即可在回测看板「因子与特征」下拉中选择。草稿仅本地编辑缓存，不会出现在看板。
        </Paragraph>
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              加载已保存组合
            </Text>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="选择后载入到编辑区…"
              value={selectedComboId}
              options={combos.map((c) => ({
                value: c.id,
                label: c.name,
              }))}
              onChange={(v) => onLoadCombo(v)}
            />
          </Col>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              组合名称（回测看板显示名）
            </Text>
            <Input
              value={comboName}
              placeholder="例如：au_5m_vol_filter_v1"
              onChange={(e) => setComboName(e.target.value)}
            />
          </Col>
          <Col span={24}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              备注（可选，显示在回测看板节点说明）
            </Text>
            <Input
              value={comboNote}
              placeholder="一句话说明本组合假设"
              onChange={(e) => setComboNote(e.target.value)}
            />
          </Col>
          <Col span={24}>
            <Space wrap>
              <Button type="primary" icon={<CloudUploadOutlined />} onClick={onSaveAsNewCombo}>
                另存为新组合
              </Button>
              <Button icon={<SaveOutlined />} onClick={onUpdateCombo} disabled={!selectedComboId}>
                覆盖更新选中
              </Button>
              <Button danger icon={<DeleteOutlined />} onClick={onDeleteCombo} disabled={!selectedComboId}>
                删除选中
              </Button>
            </Space>
          </Col>
          {combos.length > 0 && (
            <Col span={24}>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                库内一览
              </Text>
              <Space direction="vertical" style={{ width: '100%' }} size={6}>
                {combos.map((c) => (
                  <Flex
                    key={c.id}
                    justify="space-between"
                    align="center"
                    gap={8}
                    style={{
                      padding: '8px 12px',
                      borderRadius: 10,
                      background:
                        selectedComboId === c.id ? 'rgba(10,132,255,0.16)' : '#121C30',
                      border: '1px solid rgba(180, 200, 230, 0.22)',
                      cursor: 'pointer',
                    }}
                    onClick={() => onLoadCombo(c.id)}
                  >
                    <div>
                      <Text strong>{c.name}</Text>
                      <Text type="secondary" style={{ display: 'block', fontSize: 11 }}>
                        {summarizeFactorCombo(c)}
                      </Text>
                    </div>
                    <Tag>{c.config.modules.filter((m) => m.enabled).length} 启用</Tag>
                  </Flex>
                ))}
              </Space>
            </Col>
          )}
        </Row>
      </Card>

      <Card title="边界">
        <Row gutter={[12, 12]}>
          {BOUNDARY_RULES.map((r) => (
            <Col key={r.title} xs={24} md={8}>
              <Card size="small" styles={{ body: { padding: 14 } }}>
                <Tag color="blue">{r.title}</Tag>
                <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                  {r.body}
                </Text>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card
        title="纯净数据管道"
        extra={<Tag color="processing">仅 OHLCV(+OI) · 已闭合 bar</Tag>}
      >
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 16 }}>
          绕过臃肿内置指标函数：直接拿底层 K 线，多周期自己处理。高周期未闭合时只
          forward-fill 上一根已确认数据。
        </Paragraph>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              决策主周期
            </Text>
            <Select
              style={{ width: '100%' }}
              value={cfg.pipeline.baseTimeframe}
              options={TIMEFRAME_OPTIONS.map((t) => ({ value: t.id, label: t.label }))}
              onChange={(v: TimeframeId) => patchPipeline({ baseTimeframe: v })}
            />
          </Col>
          <Col xs={24} sm={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              额外周期（对齐用）
            </Text>
            <Select
              mode="multiple"
              style={{ width: '100%' }}
              value={cfg.pipeline.alignTimeframes}
              options={TIMEFRAME_OPTIONS.filter(
                (t) => t.id !== cfg.pipeline.baseTimeframe,
              ).map((t) => ({ value: t.id, label: t.label }))}
              onChange={(v: TimeframeId[]) => patchPipeline({ alignTimeframes: v })}
            />
          </Col>
          <Col xs={24} sm={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
              warmup_bars
            </Text>
            <InputNumber
              style={{ width: '100%' }}
              min={50}
              max={2000}
              value={cfg.pipeline.warmupBars}
              onChange={(v) => patchPipeline({ warmupBars: Number(v ?? 200) })}
            />
          </Col>
          <Col span={24}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              管道字段（固定；无预装指标列）
            </Text>
            <Space wrap>
              {RAW_FIELDS.map((f) => (
                <Tag key={f.id}>{f.label}</Tag>
              ))}
              <Tag color="blue">closed_bars_only = true</Tag>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card
        title="我的因子模块"
        extra={
          <Space wrap>
            <Button type="primary" icon={<PlusOutlined />} onClick={onAddModule}>
              新建模块
            </Button>
            <Button icon={<SaveOutlined />} onClick={onSaveDraft}>
              保存草稿
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          每个模块：启用开关、因子命名、触发 K 线周期、Python 编辑器。一个组合可挂多个模块。
        </Paragraph>
        {errors.length > 0 && (
          <Paragraph type="danger" style={{ fontSize: 12 }}>
            {errors.slice(0, 4).join('；')}
            {errors.length > 4 ? `…共 ${errors.length} 项` : ''}
          </Paragraph>
        )}
        {cfg.modules.length === 0 ? (
          <Text type="secondary">还没有模块。点「新建模块」开始写代码。</Text>
        ) : (
          <Tabs
            type="editable-card"
            hideAdd
            activeKey={activeModuleId}
            onChange={setActiveModuleId}
            onEdit={(targetKey, action) => {
              if (action === 'remove' && typeof targetKey === 'string') {
                setCfg((prev) => ({
                  ...prev,
                  modules: prev.modules.filter((x) => x.id !== targetKey),
                }))
              }
            }}
            tabBarExtraContent={
              <Button size="small" type="link" icon={<PlusOutlined />} onClick={onAddModule}>
                添加
              </Button>
            }
            items={cfg.modules.map((m) => ({
              key: m.id,
              label: (
                <span>
                  {m.enabled ? '' : '⏸ '}
                  {m.name || m.fileName}
                </span>
              ),
              children:
                activeModule && activeModule.id === m.id ? (
                  <ModuleEditor
                    mod={activeModule}
                    onChange={(partial) => updateModule(m.id, partial)}
                  />
                ) : null,
            }))}
          />
        )}
        <Button type="link" size="small" style={{ marginTop: 8, paddingInline: 0 }} onClick={onReset}>
          重置示范草稿
        </Button>
      </Card>

      <Card
        title="串联契约 · Feature Dict"
        extra={
          <Button size="small" icon={<CopyOutlined />} onClick={onCopyContract}>
            复制 Python 契约
          </Button>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              当前启用输出键 → 预览
            </Text>
            {keys.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                启用至少一个模块并声明输出键后，这里会出现 Feature Dict。
              </Text>
            ) : (
              <pre
                style={{
                  margin: 0,
                  padding: 14,
                  borderRadius: 12,
                  background: '#121C30',
                  border: '1px solid rgba(180, 200, 230, 0.28)',
                  color: '#F5F5F7',
                  fontSize: 12,
                  lineHeight: 1.55,
                  overflow: 'auto',
                  maxHeight: 280,
                }}
              >
                {JSON.stringify(
                  {
                    combo_name: comboName || cfg.workspaceName,
                    base_timeframe: cfg.pipeline.baseTimeframe,
                    modules: cfg.modules
                      .filter((m) => m.enabled)
                      .map((m) => m.modulePath),
                    values: preview,
                  },
                  null,
                  2,
                )}
              </pre>
            )}
          </Col>
          <Col xs={24} lg={12}>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              FactorModule 接口（主干只调用，不实现指标）
            </Text>
            <pre
              style={{
                margin: 0,
                padding: 14,
                borderRadius: 12,
                background: '#121C30',
                border: '1px solid rgba(180, 200, 230, 0.28)',
                color: '#C8D0DC',
                fontSize: 11,
                lineHeight: 1.5,
                overflow: 'auto',
                maxHeight: 280,
                whiteSpace: 'pre-wrap',
              }}
            >
              {FACTOR_MODULE_CONTRACT}
            </pre>
          </Col>
        </Row>
      </Card>
    </Flex>
  )
}
