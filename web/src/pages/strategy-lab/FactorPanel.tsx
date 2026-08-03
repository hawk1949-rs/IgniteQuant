import { useEffect, useMemo, useRef, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Flex,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { FactorCodeEditor } from './FactorCodeEditor'
import {
  DEFAULT_CATEGORY,
  TIMEFRAME_OPTIONS,
  collectCategories,
  compileRequirementToModule,
  createChatMessage,
  createDefaultMiningConfig,
  createEmptyModule,
  defaultFactorChat,
  loadFactorChat,
  loadFactorMiningConfig,
  modulePathFromFileName,
  normalizeCategory,
  persistFactorChat,
  persistFactorMiningConfig,
  sanitizePyFileName,
  validateModules,
  type FactorChatMessage,
  type FactorMiningConfig,
  type FactorModule,
  type TimeframeId,
} from './factor-data'

const { Text, Paragraph } = Typography
const { TextArea } = Input

function needsFormulaWork(mod: FactorModule): boolean {
  return /TODO|:\s*0\.0/.test(mod.source)
}

function humanError(raw: string): string {
  return raw
    .replace(/^「[^」]+」/, '')
    .replace(/Feature Dict 输出键/g, '输出名')
    .replace(/缺少 def compute\(\.\.\.\)/g, '缺少标准计算方法')
    .replace(/compute 中未见 return/g, '方法没有返回结果')
    .replace(/源码未出现声明键/g, '代码里缺少已声明的输出名')
    .replace(/须为 snake_case/g, '请用小写英文和下划线')
}

function timeframeShort(ids: TimeframeId[]): string {
  return ids
    .map((id) => TIMEFRAME_OPTIONS.find((t) => t.id === id)?.label ?? id)
    .join('、')
}

export function FactorPanel() {
  const { message } = App.useApp()
  const [cfg, setCfg] = useState<FactorMiningConfig>(() => loadFactorMiningConfig())
  const [activeModuleId, setActiveModuleId] = useState<string>(
    () => loadFactorMiningConfig().modules[0]?.id ?? '',
  )
  const [categoryFilter, setCategoryFilter] = useState('')
  const [chat, setChat] = useState<FactorChatMessage[]>(() => loadFactorChat())
  const [draft, setDraft] = useState('')
  const [codeEditable, setCodeEditable] = useState(false)
  const [categoryModalOpen, setCategoryModalOpen] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)

  const categories = useMemo(
    () => collectCategories(cfg.modules, cfg.categories),
    [cfg.modules, cfg.categories],
  )

  const categoryCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const m of cfg.modules) {
      const c = normalizeCategory(m.category)
      map.set(c, (map.get(c) ?? 0) + 1)
    }
    return map
  }, [cfg.modules])

  const filteredModules = useMemo(() => {
    if (!categoryFilter) return cfg.modules
    return cfg.modules.filter((m) => normalizeCategory(m.category) === categoryFilter)
  }, [cfg.modules, categoryFilter])

  const activeModule = cfg.modules.find((m) => m.id === activeModuleId)

  useEffect(() => {
    if (filteredModules.length === 0) {
      if (cfg.modules.length === 0) setActiveModuleId('')
      return
    }
    if (!filteredModules.some((m) => m.id === activeModuleId)) {
      setActiveModuleId(filteredModules[0].id)
    }
  }, [filteredModules, cfg.modules.length, activeModuleId])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  const activeErrors = useMemo(
    () =>
      activeModule
        ? validateModules([activeModule]).map((e) => humanError(e))
        : [],
    [activeModule],
  )

  const updateModule = (id: string, partial: Partial<FactorModule>) => {
    setCfg((prev) => {
      const modules = prev.modules.map((m) => {
        if (m.id !== id) return m
        const next = { ...m, ...partial }
        if (partial.name !== undefined) {
          const stem = partial.name.trim()
          if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(stem)) {
            const fileName = sanitizePyFileName(stem)
            next.fileName = fileName
            next.modulePath = modulePathFromFileName(fileName)
          }
        }
        return next
      })
      const nextCategories =
        partial.category !== undefined
          ? collectCategories(modules, [...prev.categories, partial.category])
          : prev.categories
      return { ...prev, modules, categories: nextCategories }
    })
  }

  const persistAll = (nextCfg: FactorMiningConfig, nextChat?: FactorChatMessage[]) => {
    persistFactorMiningConfig(nextCfg)
    if (nextChat) persistFactorChat(nextChat)
    else persistFactorChat(chat)
  }

  const confirmNewCategory = () => {
    const name = normalizeCategory(newCategoryName)
    if (!newCategoryName.trim()) {
      message.error('请输入分类名称')
      return
    }
    if (categories.includes(name)) {
      message.warning(`分类「${name}」已存在`)
      setCategoryFilter(name)
      setCategoryModalOpen(false)
      return
    }
    setCfg((prev) => {
      const next = {
        ...prev,
        categories: collectCategories(prev.modules, [...prev.categories, name]),
      }
      persistAll(next)
      return next
    })
    setCategoryFilter(name)
    setCategoryModalOpen(false)
    message.success(`已新建分类「${name}」`)
  }

  const onAddFactor = () => {
    const created = createEmptyModule(categoryFilter || DEFAULT_CATEGORY)
    setCfg((prev) => {
      const next = {
        ...prev,
        modules: [created, ...prev.modules],
        categories: collectCategories([created, ...prev.modules], prev.categories),
      }
      persistAll(next)
      return next
    })
    setActiveModuleId(created.id)
    setCodeEditable(false)
    message.success('已新建空白因子，可在下方改名并保存')
  }

  const onDeleteFactor = (id: string) => {
    setCfg((prev) => {
      const next = {
        ...prev,
        modules: prev.modules.filter((m) => m.id !== id),
      }
      persistAll(next)
      return next
    })
    if (activeModuleId === id) setActiveModuleId('')
    message.success('已删除因子')
  }

  const onSaveCurrent = () => {
    if (!activeModule) {
      message.warning('请先在列表中选择一个因子')
      return
    }
    const errs = validateModules([activeModule]).map(humanError)
    if (errs.length) {
      message.error(errs[0])
      return
    }
    persistAll(cfg)
    message.success(`已保存「${activeModule.name}」的命名、分类与代码`)
  }

  const onGenerate = () => {
    const text = draft.trim()
    if (!text) {
      message.warning('先输入要挖的概念或想法')
      return
    }
    try {
      const { module, assistantReply } = compileRequirementToModule(text, {
        category: categoryFilter || undefined,
      })
      const userMsg = createChatMessage('user', text)
      const botMsg = createChatMessage('assistant', assistantReply, { moduleId: module.id })
      setCfg((prev) => {
        const next = {
          ...prev,
          modules: [module, ...prev.modules],
          categories: collectCategories([module, ...prev.modules], prev.categories),
        }
        const nextChat = [...chat, userMsg, botMsg].slice(-80)
        persistAll(next, nextChat)
        return next
      })
      setChat((prev) => [...prev, userMsg, botMsg].slice(-80))
      setActiveModuleId(module.id)
      setCodeEditable(false)
      setDraft('')
      message.success(`已生成「${module.name}」，可在右侧改名分类后保存`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    }
  }

  const onReset = () => {
    const next = createDefaultMiningConfig()
    setCfg(next)
    persistFactorMiningConfig(next)
    const welcome = defaultFactorChat()
    setChat(welcome)
    persistFactorChat(welcome)
    setCategoryFilter('')
    setActiveModuleId(next.modules[0]?.id ?? '')
    setDraft('')
    setCodeEditable(false)
    message.success('已恢复示例')
  }

  const onCopyCode = async () => {
    if (!activeModule) return
    try {
      await navigator.clipboard.writeText(activeModule.source)
      message.success('已复制代码')
    } catch {
      message.warning('复制失败')
    }
  }

  return (
    <>
      <Row gutter={[16, 16]} align="stretch">
        <Col xs={24} lg={10} xl={9}>
          <Card
            size="small"
            title="挖因子"
            styles={{
              body: { display: 'flex', flexDirection: 'column', height: 'min(72vh, 680px)' },
            }}
          >
            <Flex
              vertical
              gap={10}
              style={{ flex: 1, overflowY: 'auto', marginBottom: 12, minHeight: 0 }}
            >
              {chat.map((m) => (
                <div
                  key={m.id}
                  style={{
                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '92%',
                    padding: '10px 12px',
                    borderRadius: 12,
                    background:
                      m.role === 'user' ? 'rgba(10, 132, 255, 0.22)' : 'rgba(18, 28, 48, 0.95)',
                    border: '1px solid rgba(180, 200, 230, 0.28)',
                    whiteSpace: 'pre-wrap',
                    fontSize: 13,
                    lineHeight: 1.55,
                  }}
                >
                  <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                    {m.role === 'user' ? '你' : '助手'}
                  </Text>
                  {m.content}
                  {m.moduleId ? (
                    <Button
                      type="link"
                      size="small"
                      style={{ paddingInline: 0, height: 'auto', marginTop: 6 }}
                      onClick={() => setActiveModuleId(m.moduleId!)}
                    >
                      在右侧查看
                    </Button>
                  ) : null}
                </div>
              ))}
              <div ref={chatEndRef} />
            </Flex>

            <TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="把要挖的东西、概念写进来。例如：5 分钟波动率过滤，波动大时少信趋势"
              autoSize={{ minRows: 3, maxRows: 5 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  onGenerate()
                }
              }}
            />
            <Flex justify="space-between" align="center" style={{ marginTop: 10 }} wrap="wrap" gap={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {categoryFilter
                  ? `新因子将归入「${categoryFilter}」`
                  : 'Enter 生成 · Shift+Enter 换行'}
              </Text>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={onGenerate}
                disabled={!draft.trim()}
              >
                生成因子
              </Button>
            </Flex>
          </Card>
        </Col>

        <Col xs={24} lg={14} xl={15}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Card
              size="small"
              title="因子列表"
              extra={
                <Space size={8} wrap>
                  <Select
                    size="small"
                    style={{ minWidth: 140 }}
                    value={categoryFilter || '__all__'}
                    options={[
                      { value: '__all__', label: `全部（${cfg.modules.length}）` },
                      ...categories.map((c) => ({
                        value: c,
                        label: `${c}（${categoryCounts.get(c) ?? 0}）`,
                      })),
                    ]}
                    onChange={(v) => setCategoryFilter(v === '__all__' ? '' : v)}
                  />
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => {
                      setNewCategoryName('')
                      setCategoryModalOpen(true)
                    }}
                  >
                    新建分类
                  </Button>
                  <Button size="small" icon={<PlusOutlined />} onClick={onAddFactor}>
                    新建因子
                  </Button>
                </Space>
              }
            >
              {filteredModules.length === 0 ? (
                <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {cfg.modules.length === 0
                    ? '还没有因子。可点「新建因子」，或在左边对话生成。'
                    : `「${categoryFilter}」下还没有因子。可换分类，或点「新建因子」。`}
                </Paragraph>
              ) : (
                <Flex vertical gap={8} style={{ maxHeight: 240, overflowY: 'auto' }}>
                  {filteredModules.map((m) => {
                    const active = m.id === activeModuleId
                    return (
                      <div
                        key={m.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '10px 12px',
                          borderRadius: 10,
                          border: active
                            ? '1px solid rgba(10, 132, 255, 0.75)'
                            : '1px solid rgba(180, 200, 230, 0.28)',
                          background: active ? 'rgba(10, 132, 255, 0.12)' : '#121C30',
                        }}
                      >
                        <button
                          type="button"
                          onClick={() => {
                            setActiveModuleId(m.id)
                            setCodeEditable(false)
                          }}
                          style={{
                            flex: 1,
                            minWidth: 0,
                            textAlign: 'left',
                            background: 'transparent',
                            border: 'none',
                            color: 'inherit',
                            cursor: 'pointer',
                            padding: 0,
                          }}
                        >
                          <Text strong style={{ display: 'block' }}>
                            {m.name}
                          </Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {normalizeCategory(m.category)} ·{' '}
                            {timeframeShort(m.requiredTimeframes)}
                          </Text>
                          <div style={{ marginTop: 6 }}>
                            <Space size={4} wrap>
                              <Tag color={m.enabled ? 'success' : 'default'}>
                                {m.enabled ? '已存入' : '未存入'}
                              </Tag>
                              <Tag color={needsFormulaWork(m) ? 'warning' : 'blue'}>
                                {needsFormulaWork(m) ? '草稿' : '有代码'}
                              </Tag>
                            </Space>
                          </div>
                        </button>
                        <Popconfirm
                          title={`删除「${m.name}」？`}
                          okText="删除"
                          cancelText="取消"
                          onConfirm={() => onDeleteFactor(m.id)}
                        >
                          <Button
                            size="small"
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            aria-label={`删除 ${m.name}`}
                          />
                        </Popconfirm>
                      </div>
                    )
                  })}
                </Flex>
              )}
              <Button
                type="link"
                size="small"
                style={{ marginTop: 8, paddingInline: 0 }}
                onClick={onReset}
              >
                恢复示例
              </Button>
            </Card>

            {activeModule ? (
              <Card
                size="small"
                title="命名 · 分类 · 代码"
                extra={
                  <Button type="primary" size="small" icon={<SaveOutlined />} onClick={onSaveCurrent}>
                    保存
                  </Button>
                }
              >
                <Flex vertical gap={14}>
                  <Row gutter={[12, 12]}>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        命名
                      </Text>
                      <Input
                        value={activeModule.name}
                        onChange={(e) => updateModule(activeModule.id, { name: e.target.value })}
                        placeholder="给这个因子起个名字"
                      />
                    </Col>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        分类
                      </Text>
                      <Select
                        style={{ width: '100%' }}
                        value={normalizeCategory(activeModule.category)}
                        options={categories.map((c) => ({ value: c, label: c }))}
                        onChange={(v) =>
                          updateModule(activeModule.id, {
                            category: v || DEFAULT_CATEGORY,
                          })
                        }
                        placeholder="在列表里新建分类后，这里选择"
                      />
                    </Col>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        看盘周期
                      </Text>
                      <Select
                        mode="multiple"
                        style={{ width: '100%' }}
                        value={activeModule.requiredTimeframes}
                        options={TIMEFRAME_OPTIONS.map((t) => ({
                          value: t.id,
                          label: t.label,
                        }))}
                        onChange={(v: TimeframeId[]) =>
                          updateModule(activeModule.id, { requiredTimeframes: v })
                        }
                      />
                    </Col>
                    <Col xs={24} sm={12}>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        存入汇总
                      </Text>
                      <Flex align="center" gap={10} style={{ height: 32 }}>
                        <Switch
                          checked={activeModule.enabled}
                          checkedChildren="开"
                          unCheckedChildren="关"
                          onChange={(v) => updateModule(activeModule.id, { enabled: v })}
                        />
                        <Tag color={needsFormulaWork(activeModule) ? 'warning' : 'success'}>
                          {needsFormulaWork(activeModule) ? '公式待完善' : '已有公式草稿'}
                        </Tag>
                      </Flex>
                    </Col>
                    <Col span={24}>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        概念说明
                      </Text>
                      <TextArea
                        value={activeModule.hypothesis}
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        onChange={(e) =>
                          updateModule(activeModule.id, { hypothesis: e.target.value })
                        }
                      />
                    </Col>
                  </Row>

                  <div>
                    <Flex
                      justify="space-between"
                      align="center"
                      wrap="wrap"
                      gap={8}
                      style={{ marginBottom: 8 }}
                    >
                      <Text strong>生成的代码</Text>
                      <Space size={8}>
                        <Button size="small" icon={<CopyOutlined />} onClick={() => void onCopyCode()}>
                          复制
                        </Button>
                        <Switch
                          size="small"
                          checked={codeEditable}
                          onChange={setCodeEditable}
                          checkedChildren="编辑"
                          unCheckedChildren="只读"
                        />
                      </Space>
                    </Flex>
                    {codeEditable ? (
                      <FactorCodeEditor
                        fileName={activeModule.fileName}
                        value={activeModule.source}
                        onChange={(source) => updateModule(activeModule.id, { source })}
                      />
                    ) : (
                      <pre
                        style={{
                          margin: 0,
                          padding: 14,
                          borderRadius: 12,
                          background: '#121C30',
                          border: '1px solid rgba(180, 200, 230, 0.28)',
                          color: '#C8D0DC',
                          fontSize: 12,
                          lineHeight: 1.5,
                          overflow: 'auto',
                          maxHeight: 320,
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {activeModule.source}
                      </pre>
                    )}
                    {activeErrors.length > 0 ? (
                      <Paragraph type="danger" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                        {activeErrors.slice(0, 3).join('；')}
                      </Paragraph>
                    ) : null}
                  </div>
                </Flex>
              </Card>
            ) : (
              <Card size="small">
                <Text type="secondary">在列表中选择或新建一个因子后，在这里改命名、分类与代码并保存。</Text>
              </Card>
            )}
          </Space>
        </Col>
      </Row>

      <Modal
        title="新建分类"
        open={categoryModalOpen}
        okText="创建"
        cancelText="取消"
        onOk={confirmNewCategory}
        onCancel={() => setCategoryModalOpen(false)}
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
          创建后会出现在列表筛选和下方「分类」下拉里；正筛选该类时，新建/对话生成的因子会归入。
        </Text>
        <Input
          autoFocus
          value={newCategoryName}
          placeholder="例如：结构 / 微观结构 / 季节性"
          onChange={(e) => setNewCategoryName(e.target.value)}
          onPressEnter={confirmNewCategory}
        />
      </Modal>
    </>
  )
}
