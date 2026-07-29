import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthGate } from './auth/AuthGate'
import { AppleAntdProvider } from './theme/AppleAntdProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppleAntdProvider>
      <AuthGate>
        <App />
      </AuthGate>
    </AppleAntdProvider>
  </StrictMode>,
)
