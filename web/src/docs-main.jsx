import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AlphaLoopDocs from './AlphaLoopDocs.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AlphaLoopDocs />
  </StrictMode>,
)
