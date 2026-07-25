import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AppleAntdProvider } from './theme/AppleAntdProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppleAntdProvider>
      <App />
    </AppleAntdProvider>
  </StrictMode>,
)
