import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell.tsx'
import { CapturePage } from './pages/CapturePage.tsx'
import { ObservationsPage } from './pages/ObservationsPage.tsx'

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CapturePage />} />
        <Route path="observations" element={<ObservationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
