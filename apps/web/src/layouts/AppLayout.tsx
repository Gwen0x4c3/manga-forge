import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { IconHome, IconFolder, IconPlus, IconBolt } from '@douyinfe/semi-icons'

export default function AppLayout() {
    const navigate = useNavigate()
    const location = useLocation()

    const navItems = [
        { key: '/', label: '创作总览', icon: <IconHome size="small" /> },
        { key: '/projects', label: '连载作品库', icon: <IconFolder size="small" /> },
    ]

    const isActive = (key: string) => {
        if (key === '/') return location.pathname === '/'
        return location.pathname.startsWith(key)
    }

    return (
        <div className="min-h-screen flex flex-col text-slate-900">
            {/* Airy Bright Daylight Glass Topbar (JP Pop × US Modern Creative Tool) */}
            <header className="sticky top-0 z-30 h-16 bg-white/85 backdrop-blur-xl border-b border-slate-200/80">
                <div className="max-w-[1480px] h-full mx-auto px-5 md:px-8 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-6">
                        {/* Energetic Pop Brand Mark */}
                        <button
                            type="button"
                            onClick={() => navigate('/')}
                            className="flex items-center gap-2.5 bg-transparent border-0 p-0 cursor-pointer group"
                        >
                            <span className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#ff5e3a] via-[#ff3b5c] to-[#f43f5e] text-white flex items-center justify-center shadow-md shadow-rose-500/25 group-hover:scale-105 group-hover:-rotate-3 transition-transform">
                                <IconBolt size="large" />
                            </span>
                            <div className="text-left">
                                <div className="flex items-center gap-2 leading-none">
                                    <span className="text-[17px] font-black tracking-tight text-slate-900">
                                        MangaForge
                                    </span>
                                    <span className="text-[10px] font-extrabold tracking-wider uppercase px-2 py-0.5 rounded-full bg-gradient-to-r from-blue-50 to-sky-50 text-blue-600 border border-blue-200/80">
                                        Studio
                                    </span>
                                </div>
                            </div>
                        </button>

                        {/* Pill Navigation */}
                        <nav className="flex items-center gap-1.5 bg-slate-100/90 p-1 rounded-full border border-slate-200/70">
                            {navItems.map((item) => {
                                const active = isActive(item.key)
                                return (
                                    <button
                                        key={item.key}
                                        type="button"
                                        onClick={() => navigate(item.key)}
                                        className={`px-4 py-1.5 rounded-full text-xs font-bold flex items-center gap-1.5 transition-all cursor-pointer border-0 ${
                                            active
                                                ? 'bg-white text-blue-600 shadow-sm'
                                                : 'bg-transparent text-slate-600 hover:text-slate-900'
                                        }`}
                                    >
                                        {item.icon}
                                        {item.label}
                                    </button>
                                )
                            })}
                        </nav>
                    </div>

                    <div className="flex items-center gap-3">
                        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200/80 text-[11px] font-semibold text-emerald-700">
                            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                            <span>Story Engine Online</span>
                        </div>
                        <button
                            type="button"
                            onClick={() => navigate('/projects?create=1')}
                            className="brand-gradient-btn px-4 py-2 rounded-full text-xs font-bold flex items-center gap-1.5 cursor-pointer"
                        >
                            <IconPlus size="small" />
                            新建连载
                        </button>
                    </div>
                </div>
            </header>

            <main className="flex-1 min-w-0">
                <div className="max-w-[1480px] mx-auto px-5 py-6 md:px-8 md:py-7">
                    <Outlet />
                </div>
            </main>
        </div>
    )
}
