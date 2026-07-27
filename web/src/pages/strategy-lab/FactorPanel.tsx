import { useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Flex,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined, SaveOutlined, CopyOutlined } from '@ant-design/icons'
import { FactorCodeEditor } from './FactorCodeEditor'
import {
  BOUNDARY_RULES,
  DEFAULT_CATEGORY,
  FACTOR_MODULE_CONTRACT,
  TIMEFRAME_OPTIONS,
  buildFeatureDictPreview,
  collectCategories,
  collectOutputKeys,
  createDefaultMiningConfig,
  createEmptyModule,
  loadFactorMiningConfig,
  modulePathFromFileName,
  normalizeCategory,
  persistFactorMiningConfig,
  sanitizePyFileName,
  validateModules,
  type FactorMiningConfig,
  type FactorModule,
  type TimeframeId,
} from './factor-data'

const { Text, Paragraph } = Typography

function ModuleEditor({
  mod,
  onChange,
}: {
  mod: FactorModule
  onChange: (partial: Partial<FactorModule>) => void
}) {
  const renameFactor = (name: string) => {
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
  const { message } = App.useApp()
  const [cfg, setCfg] = useState<FactorMiningConfig>(() => loadFactorMiningConfig())
  const [activeModuleId, setActiveModuleId] = useState<string>(
    () => loadFactorMiningConfig().modules[0]?.id ?? '',
  )
  /** 空字符串 = 显示全部分类 */
  const [categoryFilter, setCategoryFilter] = useState<string>('')
  const [categoryModalOpen, setCategoryModalOpen] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')

  const categories = useMemo(
    () => collectCategories(cfg.modules, cfg.categories),
    [cfg.modules, cfg.categories],
  )

  const filteredModules = useMemo(() => {
    if (!categoryFilter) return cfg.modules
    return cfg.modules.filter(
      (m) => normalizeCategory(m.category) === categoryFilter,
    )
  }, [cfg.modules, categoryFilter])

  useEffect(() => {
    if (filteredModules.length === 0) {
      if (cfg.modules.length === 0) setActiveModuleId('')
      return
    }
    if (!filteredModules.some((m) => m.id === activeModuleId)) {
      setActiveModuleId(filteredModules[0].id)
    }
  }, [filteredModules, cfg.modules.length, activeModuleId])

  const activeModule = cfg.modules.find((m) => m.id === activeModuleId)
  const errors = useMemo(() => validateModules(cfg.modules), [cfg.modules])
  const keys = useMemo(() => collectOutputKeys(cfg.modules), [cfg.modules])
  const preview = useMemo(() => buildFeatureDictPreview(cfg), [cfg])

  const updateModule = (id: string, partial: Partial<FactorModule>) => {
    setCfg((prev) => {
      const modules = prev.modules.map((m) => (m.id === id ? { ...m, ...partial } : m))
      const categories =
        partial.category !== undefined
          ? collectCategories(modules, [...prev.categories, partial.category])
          : prev.categories
      return { ...prev, modules, categories }
    })
  }

  const onSaveDraft = () => {
    if (errors.length) {
      message.error(errors[0])
      return
    }
    persistFactorMiningConfig(cfg)
    message.success('已保存因子挖掘草稿')
  }

  const onReset = () => {
    const next = createDefaultMiningConfig()
    setCfg(next)
    persistFactorMiningConfig(next)
    setCategoryFilter('')
    setActiveModuleId(next.modules[0]?.id ?? '')
    message.success('已重置为示范草稿')
  }

  const onAddModule = () => {
    const next = createEmptyModule(categoryFilter || DEFAULT_CATEGORY)
    setCfg((prev) => ({
      ...prev,
      modules: [...prev.modules, next],
      categories: collectCategories([...prev.modules, next], prev.categories),
    }))
    setActiveModuleId(next.id)
  }

  const openCategoryModal = () => {
    setNewCategoryName('')
    setCategoryModalOpen(true)
  }

  const confirmAddCategory = () => {
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
    setCfg((prev) => ({
      ...prev,
      categories: collectCategories(prev.modules, [...prev.categories, name]),
    }))
    setCategoryFilter(name)
    setCategoryModalOpen(false)
    message.success(`已创建分类「${name}」`)
  }

  const onCopyContract = async () => {
    try {
      await navigator.clipboard.writeText(FACTOR_MODULE_CONTRACT)
      message.success('已复制 FactorModule 契约到剪贴板')
    } catch {
      message.warning('复制失败，请手动选中下方代码')
    }
  }

  const categoryCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const m of cfg.modules) {
      const c = normalizeCategory(m.category)
      map.set(c, (map.get(c) ?? 0) + 1)
    }
    return map
  }, [cfg.modules])

  return (
    <Flex vertical gap={12}>
      <Card size="small" styles={{ body: { padding: '10px 12px' } }}>
        <Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12, maxWidth: 720 }}>
          写自己的 <Text code>compute</Text>，按归类管理因子；非预装指标陈列。
        </Paragraph>
        <Row gutter={[8, 8]}>
          {BOUNDARY_RULES.map((r) => (
            <Col key={r.title} xs={24} md={8}>
              <Card size="small" styles={{ body: { padding: '8px 10px' } }}>
                <Tag color="blue">{r.title}</Tag>
                <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>
                  {r.body}
                </Text>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card
        size="small"
        title="因子编译与挖掘"
        extra={
          <Space wrap size={8}>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCategoryModal}>
              新建分类
            </Button>
            <Button size="small" icon={<PlusOutlined />} onClick={onAddModule}>
              添加因子
            </Button>
            <Button size="small" icon={<SaveOutlined />} onClick={onSaveDraft}>
              保存草稿
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 10 }}>
          先选或新建分类，再用「添加因子」编译。每个因子：启用、命名、触发周期、Python 源码。
        </Paragraph>

        <Flex wrap="wrap" gap={8} align="center" style={{ marginBottom: 14 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            按归类筛选
          </Text>
          <Select
            allowClear
            style={{ minWidth: 180 }}
            placeholder="全部归类"
            value={categoryFilter || undefined}
            options={categories.map((c) => ({
              value: c,
              label: `${c}（${categoryCounts.get(c) ?? 0}）`,
            }))}
            onChange={(v) => setCategoryFilter(v ?? '')}
          />
          {categoryFilter ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前：{categoryFilter} · 添加因子将归入此类
            </Text>
          ) : null}
        </Flex>

        {errors.length > 0 && (
          <Paragraph type="danger" style={{ fontSize: 12 }}>
            {errors.slice(0, 4).join('；')}
            {errors.length > 4 ? `…共 ${errors.length} 项` : ''}
          </Paragraph>
        )}

        {filteredModules.length === 0 ? (
          <Flex
            vertical
            align="center"
            justify="center"
            gap={12}
            style={{
              padding: '36px 16px',
              borderRadius: 12,
              border: '1px dashed rgba(180, 200, 230, 0.35)',
              background: '#121C30',
            }}
          >
            <Text type="secondary" style={{ textAlign: 'center', maxWidth: 420 }}>
              {categoryFilter
                ? `「${categoryFilter}」下还没有因子。点击下方按钮，在此分类中新建一个。`
                : '还没有因子。可先筛选或新建分类，再添加因子开始编译。'}
            </Text>
            <Button type="primary" icon={<PlusOutlined />} onClick={onAddModule}>
              {categoryFilter ? `在「${categoryFilter}」下添加因子` : '添加因子'}
            </Button>
          </Flex>
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
                添加因子
              </Button>
            }
            items={filteredModules.map((m) => ({
              key: m.id,
              label: (
                <span>
                  {m.enabled ? '' : '⏸ '}
                  <Tag style={{ marginInlineEnd: 6 }}>{normalizeCategory(m.category)}</Tag>
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

      <Modal
        title="新建分类"
        open={categoryModalOpen}
        okText="创建"
        cancelText="取消"
        onOk={confirmAddCategory}
        onCancel={() => setCategoryModalOpen(false)}
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
          分类用于归组筛选；创建后可在筛选中选中，再「添加因子」。
        </Text>
        <Input
          autoFocus
          value={newCategoryName}
          placeholder="例如：结构 / 微观结构"
          onChange={(e) => setNewCategoryName(e.target.value)}
          onPressEnter={confirmAddCategory}
        />
      </Modal>

      <Card
        size="small"
        title="Feature Dict 预览"
        extra={
          <Button size="small" icon={<CopyOutlined />} onClick={onCopyContract}>
            复制 Python 契约
          </Button>
        }
      >
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={12}>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>
              当前启用输出（契约形状）
            </Text>
            {keys.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                启用至少一个因子后，这里预览 Feature Dict。
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
                    modules: cfg.modules
                      .filter((m) => m.enabled)
                      .map((m) => ({
                        name: m.name,
                        category: normalizeCategory(m.category),
                        path: m.modulePath,
                      })),
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
              FactorModule 接口
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
