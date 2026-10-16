import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'
import App from './app/App'
import { useApp } from './app/store'
import './styles/index.css'

registerSW({ immediate: true })

// Login link: "#token=..." configures this browser, then the fragment is removed from the address bar and history.
const hashToken = new URLSearchParams(location.hash.slice(1)).get('token')
if (hashToken) {
  useApp.getState().set({ token: hashToken, mode: 'live' })
  history.replaceState(null, '', location.pathname + location.search)
}
const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
