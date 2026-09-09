import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { BookOpen, LayoutDashboard, MessageSquare, Search as SearchIcon, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'
import { MOCK_MODE } from './api/client'
import Dashboard from './pages/Dashboard'
import CaseDetail from './pages/CaseDetail'
import NewCase from './pages/NewCase'
import ScreeningResult from './pages/ScreeningResult'
import Evaluation from './pages/Evaluation'
import Chat from './pages/Chat'
import SearchPage from './pages/Search'
import Guide from './pages/Guide'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/search', label: 'Search', icon: SearchIcon },
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/guide', label: 'Guide', icon: BookOpen },
]

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-deloitte-green" />
            <span className="text-sm font-bold tracking-tight">Conflict Screening Assistant</span>
            <span className="text-xs text-slate-400">SEA T&amp;T</span>
          </div>
          <nav className="flex items-center gap-1">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) => clsx(
                  'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition',
                  isActive ? 'bg-slate-100 text-slate-900' : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {MOCK_MODE && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                MOCK MODE
              </span>
            )}
            <span className="text-xs text-slate-400">Drafting aid — not an approval engine</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cases/new" element={<NewCase />} />
          <Route path="/cases/:caseId" element={<CaseDetail />} />
          <Route path="/cases/:caseId/eval" element={<Evaluation />} />
          <Route path="/cases/:caseId/chat" element={<Chat />} />
          <Route path="/screenings/:screeningId" element={<ScreeningResult />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/guide" element={<Guide />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
