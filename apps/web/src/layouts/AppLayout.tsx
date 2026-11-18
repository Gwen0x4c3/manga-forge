import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { IconHome, IconFolder, IconBolt } from '@douyinfe/semi-icons'

export default function AppLayout() {
    const navigate = useNavigate()
    const location = useLocation()

    const navItems = [
        { key: '/', label: '创作总览', desc: '工作台与流程导览', icon: <IconHome size="large" /> },
        { key: '/projects', label: '连载作品库', desc: '漫画理解与续画工程', icon: <IconFolder size="large" /> },
    ]

    const isActive = (key: string) => {
        if (key === '/') return location.pathname === '/'
        return location.pathname.startsWith(key)
    }

    return (
        <div className="min-h-screen flex bg-slate-50 text-slate-900">
            <aside className="w-60 shrink-0 bg-slate-950 text-slate-200 flex flex-col justify-between border-r border-slate-800">
                <div>
                    <div
                        className="px-5 py-5 border-b border-slate-800/80 flex items-center gap-3 cursor-pointer"
                        onClick={() => navigate('/')}
                    >
                        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white font-bold shadow-lg shadow-indigo-500/25">
                            <IconBolt />
                        </div>
                        <div>
                            <div className="text-base font-bold tracking-tight text-white">MangaForge</div>
                            <div className="text-[11px] text-slate-400">AI 连载漫画理解与续画工坊</div>
                        </div>
                    </div>

                    <nav className="p-3 space-y-1.5">
                        {navItems.map((item) => {
                            const active = isActive(item.key)
                            return (
                                <button
                                    key={item.key}
                                    type="button"
                                    onClick={() => navigate(item.key)}
                                    className={`w-full text-left px-3.5 py-2.5 rounded-xl flex items-center gap-3 transition-all cursor-pointer border-0 ${
                                        active
                                            ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/25'
                                            : 'bg-transparent text-slate-300 hover:bg-slate-900 hover:text-white'
                                    }`}
                                >
                                    <span className={active ? 'text-white' : 'text-slate-400'}>{item.icon}</span>
                                    <div className="min-w-0">
                                        <div className="text-sm font-medium leading-tight">{item.label}</div>
                                        <div className={`text-[11px] truncate ${active ? 'text-indigo-200' : 'text-slate-500'}`}>
                                            {item.desc}
                                        </div>
                                    </div>
                                </button>
                            )
                        })}
                    </nav>
                </div>

                <div className="p-4 m-3 rounded-xl bg-slate-900/90 border border-slate-800 text-xs text-slate-400 space-y-1.5">
                    <div className="text-slate-200 font-medium flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
                        全链路记忆引擎已就绪
                    </div>
                    <p className="leading-relaxed text-[11px] text-slate-400 m-0">
                        多模态读图 · 角色/物品/场景识别 · 主线伏笔追踪 · 分镜审校与参考图一致生图
                    </p>
                </div>
            </aside>

            <main className="flex-1 min-w-0 overflow-x-hidden">
                <div className="max-w-[1440px] mx-auto px-6 py-6 md:px-8 md:py-7">
                    <Outlet />
                </div>
            </main>
        </div>
    )
}
