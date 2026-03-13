import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AlphaLoopMcp from './AlphaLoopMcp.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AlphaLoopMcp />
  </StrictMode>,
)
