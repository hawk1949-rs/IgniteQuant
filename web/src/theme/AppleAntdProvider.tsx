import { ConfigProvider, theme, App as AntApp } from 'antd'
import type { ReactNode } from 'react'
import zhCN from 'antd/locale/zh_CN'
import 'dayjs/locale/zh-cn'

/**
 * Apple Dark + 深蓝底，但刻意提高对比度：
 * 正文接近白、次要文字不要灰到看不清、边框与卡片底更实。
 */
const appleDarkTokens = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#0A84FF',
    colorInfo: '#0A84FF',
    colorSuccess: '#32D74B',
    colorWarning: '#FFD60A',
    colorError: '#FF453A',
    colorTextBase: '#FFFFFF',
    colorText: '#F5F5F7',
    colorTextSecondary: '#C8D0DC',
    colorTextTertiary: '#A8B2C2',
    colorTextQuaternary: '#8B96A8',
    colorBgBase: '#070D18',
    colorBgContainer: '#1A2740',
    colorBgElevated: '#243352',
    colorBgLayout: '#070D18',
    colorFillSecondary: 'rgba(255, 255, 255, 0.08)',
    colorFillTertiary: 'rgba(255, 255, 255, 0.06)',
    colorBorder: 'rgba(180, 200, 230, 0.42)',
    colorBorderSecondary: 'rgba(160, 180, 210, 0.32)',
    colorSplit: 'rgba(180, 200, 230, 0.28)',
    borderRadius: 12,
    borderRadiusLG: 16,
    borderRadiusSM: 10,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    fontSize: 14,
    controlHeight: 40,
    wireframe: false,
  },
  components: {
    Card: {
      colorBgContainer: '#1A2740',
      colorBorderSecondary: 'rgba(180, 200, 230, 0.38)',
      paddingLG: 20,
      borderRadiusLG: 16,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      borderRadius: 12,
      fontWeight: 600,
      defaultColor: '#F5F5F7',
      defaultBorderColor: 'rgba(180, 200, 230, 0.45)',
      defaultBg: '#243352',
    },
    Input: {
      colorBgContainer: '#121C30',
      colorText: '#F5F5F7',
      colorTextPlaceholder: '#A8B2C2',
      activeBorderColor: '#0A84FF',
      hoverBorderColor: 'rgba(10, 132, 255, 0.7)',
      activeShadow: '0 0 0 2px rgba(10, 132, 255, 0.28)',
    },
    InputNumber: {
      colorBgContainer: '#121C30',
      colorText: '#F5F5F7',
      colorTextPlaceholder: '#A8B2C2',
    },
    Select: {
      colorBgContainer: '#121C30',
      colorText: '#F5F5F7',
      colorTextPlaceholder: '#A8B2C2',
      optionSelectedBg: 'rgba(10, 132, 255, 0.28)',
      optionActiveBg: 'rgba(10, 132, 255, 0.16)',
    },
    DatePicker: {
      colorBgContainer: '#121C30',
      colorText: '#F5F5F7',
      colorTextPlaceholder: '#A8B2C2',
    },
    Table: {
      headerBg: '#121C30',
      headerColor: '#E8ECF2',
      rowHoverBg: 'rgba(10, 132, 255, 0.14)',
      borderColor: 'rgba(180, 200, 230, 0.32)',
      colorText: '#F5F5F7',
    },
    Switch: {
      colorPrimary: '#0A84FF',
      handleSize: 22,
      trackHeight: 28,
      trackMinWidth: 52,
    },
    Segmented: {
      itemSelectedBg: '#0A84FF',
      itemSelectedColor: '#FFFFFF',
      itemColor: '#C8D0DC',
      trackBg: '#121C30',
    },
    Typography: {
      colorTextDescription: '#C8D0DC',
      colorTextSecondary: '#C8D0DC',
    },
    Message: {
      contentBg: '#243352',
      colorText: '#F5F5F7',
    },
    Modal: {
      contentBg: '#1A2740',
      headerBg: '#1A2740',
    },
  },
}

export function AppleAntdProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider locale={zhCN} theme={appleDarkTokens}>
      <AntApp message={{ maxCount: 3 }} notification={{ placement: 'topRight' }}>
        {children}
      </AntApp>
    </ConfigProvider>
  )
}
