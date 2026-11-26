import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { IconHome, IconFolder, IconPlus } from '@douyinfe/semi-icons'

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
        <div className="min-h-screen flex flex-col text-[#13151b]">
            {/* Sleek Editorial Sumi-Ink Top Bar — full-width studio canvas below */}
            <header className="sticky top-0 z-30 h-14 bg-[#12141b]/95 backdrop-blur-md border-b border-white/10 text-white">
                <div className="max-w-[1480px] h-full mx-auto px-5 md:px-8 flex items-center justify-between gap-4">
                    <div className="flex items-center gap-7">
                        {/* Manga Stamp Brand Mark */}
                        <button
                            type="button"
                            onClick={() => navigate('/')}
                            className="flex items-center gap-2.5 bg-transparent border-0 p-0 cursor-pointer group"
                        >
                            <span className="w-8 h-8 rounded-lg bg-[#e11d48] text-white font-black text-sm tracking-tighter flex items-center justify-center shadow-md shadow-rose-600/30 group-hover:scale-105 transition-transform">
                                漫
                            </span>
                            <div className="text-left">
                                <div className="flex items-center gap-1.5 leading-none">
                                    <span className="text-[15px] font-extrabold tracking-tight text-white">
                                        MangaForge
                                    </span>
                                    <span className="text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded bg-white/10 text-rose-300 border border-white/10">
                                        Studio
                                    </span>
                                </div>
                            </div>
                        </button>

                        {/* Primary Navigation */}
                        <nav className="flex items-center gap-1">
                            {navItems.map((item) => {
                                const active = isActive(item.key)
                                return (
                                    <button
                                        key={item.key}
                                        type="button"
                                        onClick={() => navigate(item.key)}
                                        className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer border-0 ${
                                            active
                                                ? 'bg-white text-[#12141b] shadow-sm'
                                                : 'bg-transparent text-slate-300 hover:text-white hover:bg-white/10'
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
                        <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-[11px] text-slate-300">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            <span>长程记忆与图谱引擎就绪</span>
                        </div>
                        <button
                            type="button"
                            onClick={() => navigate('/projects?create=1')}
                            className="px-3 py-1.5 rounded-lg bg-[#e11d48] hover:bg-rose-500 text-white text-xs font-bold flex items-center gap-1.5 border-0 cursor-pointer shadow-sm shadow-rose-600/30 transition"
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
