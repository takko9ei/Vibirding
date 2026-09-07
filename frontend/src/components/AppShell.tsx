import { NavLink, Outlet } from 'react-router-dom'

function navClassName({ isActive }: { isActive: boolean }) {
  return isActive ? 'top-nav__link top-nav__link--active' : 'top-nav__link'
}

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/" aria-label="Vibirding 首页">
          <span className="brand__mark" aria-hidden="true">
            V.
          </span>
          <span className="brand__name">VIBIRDING</span>
        </NavLink>

        <nav className="top-nav" aria-label="主导航">
          <NavLink className={navClassName} end to="/">
            记一笔
          </NavLink>
          <NavLink className={navClassName} to="/observations">
            观察记录
          </NavLink>
        </nav>

        <span className="mode-badge">个人观察台 · V2</span>
      </header>

      <main className="page-shell">
        <Outlet />
      </main>
    </div>
  )
}
