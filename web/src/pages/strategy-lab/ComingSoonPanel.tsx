import { Card, Typography } from 'antd'

const { Title, Paragraph, Text } = Typography

type Props = {
  title: string
  english: string
  summary: string
}

/** 侧栏新模块占位页，后续在此替换为真实面板。 */
export function ComingSoonPanel({ title, english, summary }: Props) {
  return (
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
        {english}
      </Text>
      <Title level={3} style={{ marginTop: 8, marginBottom: 8, color: '#F5F5F7' }}>
        {title}
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 520 }}>
        {summary}
      </Paragraph>
      <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
        模块骨架已就绪，功能将在后续迭代接入。
      </Paragraph>
    </Card>
  )
}
