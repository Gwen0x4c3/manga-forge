import { Outlet, useNavigate, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Select } from '@douyinfe/semi-ui'
import { projectService } from '@/services/project'
import { useAppStore } from '@/stores/app'
import {
    MangaForgeLogo,
    IconHome,
    IconBook,
    IconChapters,
    IconGraph,
    IconTimeline,
    IconResearch,
    IconBranch,
    IconAssets,
    IconImport,
    IconSidebarToggle,
    IconSun,
    IconMoon,
    IconPlus,
    IconTelemetry,
} from '@/components/StudioIcons'

const PROJECT_VIEW_ITEMS = [
    { key: 'episodes', label: '章节目录', icon: IconChapters },
    { key: 'characters', label: '人物关系图谱', icon: IconGraph },
    { key: 'pits', label: '伏笔追踪', icon: IconTimeline },
    { key: 'qa', label: '剧情侦探 QA', icon: IconResearch },
    { key: 'story', label: '世界观与设定', icon: IconBook },
    { key: 'branches', label: '平行世界线', icon: IconBranch },
    { key: 'assets', label: '创作资产库', icon: IconAssets },
    { key: 'usage', label: '模型用量', icon: IconTelemetry },
]

const VIEW_LABELS: Record<string, string> = {
    episodes: '章节目录',
    characters: '人物关系图谱',
    pits: '伏笔追踪',
    qa: '剧情侦探 QA',
    story: '世界观与设定',
    branches: '平行世界线',
    assets: '创作资产库',
    usage: '模型用量',
}

export default function AppLayout() {
    const navigate = useNavigate()
    const location = useLocation()
    const params = useParams<{ id?: string; projectId?: string; episodeId?: string }>()
    const [searchParams] = useSearchParams()
    const { theme, toggleTheme, sidebarCollapsed, toggleSidebar } = useAppStore()

    const activeProjectId = params.projectId || params.id || null
    const currentView = searchParams.get('view') || 'episodes'
    const isEditorRoute = location.pathname.endsWith('/generate')
    const isEpisodeRoute = Boolean(params.episodeId) && !isEditorRoute
    const isMangaDexRoute = location.pathname.includes('/imports/mangadex')

    const { data: projectsData } = useQuery({
        queryKey: ['projects-nav'],
        queryFn: () => projectService.list(undefined, { page: 1, page_size: 30 }),
        staleTime: 30_000,
    })

    const projects = projectsData?.items || []
    const activeProject = projects.find((p) => p.id === activeProjectId) || null

    const breadcrumbLeaf = isEditorRoute
        ? '漫画编辑器'
        : isEpisodeRoute
          ? '章节阅读与原稿'
          : isMangaDexRoute
            ? 'MangaDex 导入'
            : activeProjectId
              ? VIEW_LABELS[currentView] || '章节目录'
              : location.pathname.startsWith('/usage')
                ? '模型用量与作图日志'
                : location.pathname.startsWith('/projects')
                  ? '连载作品库'
                  : '工作台概览'

    const isFullBleedWorkspace =
        isEditorRoute ||
        (Boolean(activeProjectId) &&
            !isEpisodeRoute &&
            !isMangaDexRoute &&
            ['characters', 'pits', 'qa'].includes(currentView))

    return (
        <div
            className="h-screen w-screen overflow-hidden flex flex-col"
            style={{ backgroundColor: 'var(--bg-app)', color: 'var(--text-primary)' }}
        >
            {/* Compact Desktop-First Studio Topbar (44px) */}
            <header
                className="h-11 shrink-0 border-b px-3 flex items-center justify-between gap-3 select-none z-30"
                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
            >
                <div className="flex items-center gap-2 min-w-0">
                    <button
                        type="button"
                        onClick={toggleSidebar}
                        title={sidebarCollapsed ? '展开导航栏' : '折叠导航栏'}
                        className="w-7 h-7 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer transition-colors shrink-0"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconSidebarToggle size={15} />
                    </button>

                    <button
                        type="button"
                        onClick={() => navigate('/')}
                        className="flex items-center gap-2 bg-transparent border-0 p-1 rounded hover:bg-[var(--bg-hover)] cursor-pointer transition-colors shrink-0"
                        style={{ color: 'var(--text-primary)' }}
                    >
                        <MangaForgeLogo size={18} />
                        <span className="text-[13px] font-semibold tracking-tight">MangaForge</span>
                    </button>

                    <span style={{ color: 'var(--border)' }}>/</span>

                    {/* Project Switcher */}
                    {projects.length > 0 ? (
                        <Select
                            size="small"
                            value={activeProjectId || '__all__'}
                            onChange={(v) => {
                                const val = String(v)
                                if (val === '__all__') {
                                    navigate('/projects')
                                } else {
                                    navigate(`/projects/${val}?view=episodes`)
                                }
                            }}
                            style={{ width: 224, maxWidth: '30vw', backgroundColor: 'transparent' }}
                            borderless
                        >
                            <Select.Option value="__all__">全部连载作品</Select.Option>
                            {projects.map((p) => (
                                <Select.Option key={p.id} value={p.id}>
                                    {p.title}
                                </Select.Option>
                            ))}
                        </Select>
                    ) : (
                        <button
                            type="button"
                            onClick={() => navigate('/projects')}
                            className="text-xs bg-transparent border-0 cursor-pointer px-1.5 py-1 rounded hover:bg-[var(--bg-hover)]"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            连载作品库
                        </button>
                    )}

                    {(activeProject || location.pathname.startsWith('/usage')) && (
                        <>
                            <span style={{ color: 'var(--border)' }}>/</span>
                            <span
                                className="text-[13px] font-medium truncate"
                                style={{ color: 'var(--text-primary)' }}
                            >
                                {breadcrumbLeaf}
                            </span>
                        </>
                    )}
                </div>

                {/* Right Global Controls */}
                <div className="flex items-center gap-2 shrink-0">
                    <div
                        className="hidden xl:flex items-center gap-1.5 text-[11px] px-2 py-1 rounded border whitespace-nowrap"
                        style={{
                            color: 'var(--text-secondary)',
                            borderColor: 'var(--border-subtle)',
                            backgroundColor: 'var(--bg-app)',
                        }}
                    >
                        <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{ backgroundColor: 'var(--status-ok)' }}
                        />
                        <span>记忆引擎已同步</span>
                    </div>

                    <button
                        type="button"
                        onClick={toggleTheme}
                        title={theme === 'dark' ? '切换至原稿纸浅色模式' : '切换至深墨工作台模式'}
                        className="h-7 px-2 rounded border flex items-center gap-1.5 text-[11px] font-medium cursor-pointer transition-colors hover:bg-[var(--bg-hover)]"
                        style={{
                            backgroundColor: 'transparent',
                            borderColor: 'var(--border)',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        {theme === 'dark' ? <IconSun size={13} /> : <IconMoon size={13} />}
                        <span className="hidden sm:inline">{theme === 'dark' ? '原稿纸' : '深墨'}</span>
                    </button>

                    <button
                        type="button"
                        onClick={() => navigate('/projects?create=1')}
                        className="h-7 px-2.5 rounded border-0 flex items-center gap-1 text-xs font-medium text-white cursor-pointer transition-colors"
                        style={{ backgroundColor: 'var(--accent)' }}
                    >
                        <IconPlus size={13} />
                        <span>新建作品</span>
                    </button>
                </div>
            </header>

            {/* Studio Body: Left Collapsible Sidebar + Center Maximized Workspace */}
            <div className="flex-1 min-h-0 flex overflow-hidden">
                <aside
                    className="shrink-0 border-r flex flex-col justify-between transition-[width] duration-150 select-none overflow-y-auto"
                    style={{
                        width: sidebarCollapsed ? 48 : 224,
                        backgroundColor: 'var(--bg-panel)',
                        borderColor: 'var(--border)',
                    }}
                >
                    <div className="py-3 space-y-4">
                        {/* Global Navigation */}
                        <div className="px-2 space-y-0.5">
                            {!sidebarCollapsed && (
                                <div
                                    className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider"
                                    style={{ color: 'var(--text-muted)' }}
                                >
                                    工作室
                                </div>
                            )}
                            {[
                                { path: '/', label: '工作台概览', icon: IconHome, active: location.pathname === '/' },
                                {
                                    path: '/projects',
                                    label: '连载作品库',
                                    icon: IconBook,
                                    active: location.pathname === '/projects',
                                },
                                {
                                    path: '/usage',
                                    label: '用量与作图日志',
                                    icon: IconTelemetry,
                                    active: location.pathname === '/usage',
                                },
                            ].map((item) => {
                                const Icon = item.icon
                                return (
                                    <button
                                        key={item.path}
                                        type="button"
                                        title={item.label}
                                        onClick={() => navigate(item.path)}
                                        className={`w-full h-9 px-2.5 rounded flex items-center gap-2.5 text-[13.5px] border-0 cursor-pointer transition-colors relative ${
                                            sidebarCollapsed ? 'justify-center px-0' : ''
                                        }`}
                                        style={{
                                            backgroundColor: item.active ? 'var(--bg-elevated)' : 'transparent',
                                            color: item.active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                            fontWeight: item.active ? 600 : 400,
                                        }}
                                    >
                                        {item.active && (
                                            <span
                                                className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r"
                                                style={{ backgroundColor: 'var(--accent)' }}
                                            />
                                        )}
                                        <Icon size={16} />
                                        {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                                    </button>
                                )
                            })}
                        </div>

                        {/* Contextual Project Navigation */}
                        {activeProjectId && (
                            <div className="px-2 space-y-0.5 pt-2.5 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                                {!sidebarCollapsed && (
                                    <div
                                        className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider truncate"
                                        style={{ color: 'var(--text-muted)' }}
                                    >
                                        {activeProject?.title || '当前连载'}
                                    </div>
                                )}
                                {PROJECT_VIEW_ITEMS.map((item) => {
                                    const Icon = item.icon
                                    const active =
                                        !isEpisodeRoute &&
                                        !isEditorRoute &&
                                        !isMangaDexRoute &&
                                        currentView === item.key
                                    return (
                                        <button
                                            key={item.key}
                                            type="button"
                                            title={item.label}
                                            onClick={() => navigate(`/projects/${activeProjectId}?view=${item.key}`)}
                                            className={`w-full h-9 px-2.5 rounded flex items-center gap-2.5 text-[13.5px] border-0 cursor-pointer transition-colors relative hover:bg-[var(--bg-hover)] ${
                                                sidebarCollapsed ? 'justify-center px-0' : ''
                                            }`}
                                            style={{
                                                backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                                                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                                fontWeight: active ? 600 : 400,
                                            }}
                                        >
                                            {active && (
                                                <span
                                                    className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r"
                                                    style={{ backgroundColor: 'var(--accent)' }}
                                                />
                                            )}
                                            <Icon size={16} />
                                            {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                                        </button>
                                    )
                                })}

                                <div className="pt-2 mt-2 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                                    <button
                                        type="button"
                                        title="MangaDex 导入"
                                        onClick={() => navigate(`/projects/${activeProjectId}/imports/mangadex`)}
                                        className={`w-full h-9 px-2.5 rounded flex items-center gap-2.5 text-[13.5px] border-0 cursor-pointer transition-colors hover:bg-[var(--bg-hover)] ${
                                            sidebarCollapsed ? 'justify-center px-0' : ''
                                        }`}
                                        style={{
                                            backgroundColor: isMangaDexRoute ? 'var(--bg-elevated)' : 'transparent',
                                            color: isMangaDexRoute ? 'var(--text-primary)' : 'var(--text-secondary)',
                                        }}
                                    >
                                        <IconImport size={16} />
                                        {!sidebarCollapsed && <span className="truncate">MangaDex 导入</span>}
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* Quick Series List when outside a project */}
                        {!activeProjectId && !sidebarCollapsed && projects.length > 0 && (
                            <div className="px-2 space-y-0.5 pt-2.5 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                                <div
                                    className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider"
                                    style={{ color: 'var(--text-muted)' }}
                                >
                                    最近作品
                                </div>
                                {projects.slice(0, 6).map((p) => (
                                    <button
                                        key={p.id}
                                        type="button"
                                        onClick={() => navigate(`/projects/${p.id}?view=episodes`)}
                                        className="w-full h-8 px-2.5 rounded flex items-center justify-between gap-2 text-[13px] border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer transition-colors"
                                        style={{ color: 'var(--text-secondary)' }}
                                    >
                                        <span className="truncate">{p.title}</span>
                                        <span className="text-xs font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
                                            {p.episode_count ?? 0}话
                                        </span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {!sidebarCollapsed && (
                        <div
                            className="px-3.5 py-2.5 border-t text-[11px] flex items-center justify-between"
                            style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}
                        >
                            <span>Ink & Paper</span>
                            <span className="font-mono text-[10px]">v2.0</span>
                        </div>
                    )}
                </aside>

                {/* Main Core Workspace */}
                <main
                    className={`flex-1 min-w-0 min-h-0 ${
                        isFullBleedWorkspace ? 'overflow-hidden flex flex-col' : 'overflow-y-auto'
                    }`}
                >
                    {isFullBleedWorkspace ? (
                        <div className="flex-1 min-h-0 flex flex-col">
                            <Outlet />
                        </div>
                    ) : (
                        <div className="max-w-[1380px] mx-auto px-6 py-6">
                            <Outlet />
                        </div>
                    )}
                </main>
            </div>
        </div>
    )
}
