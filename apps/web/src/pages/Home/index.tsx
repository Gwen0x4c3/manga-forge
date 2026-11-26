import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Spin } from '@douyinfe/semi-ui'
import { useQuery } from '@tanstack/react-query'
import { projectService, storageFileUrl } from '@/services/project'
import { IconPlus, IconBook, IconGraph, IconTimeline, IconResearch } from '@/components/StudioIcons'

const WORKFLOW_STAGES = [
    {
        code: '01',
        title: '原稿导入与归档',
        desc: '导入本地图片、ZIP 或 MangaDex 连载，按分支维护章节谱系。',
    },
    {
        code: '02',
        title: '多模态剧情解析',
        desc: '提取事件、角色生命状态迭代、逐页对白并裁切视觉参考图。',
    },
    {
        code: '03',
        title: '知识图谱与伏笔账本',
        desc: '通过人物关系图、伏笔甘特轨道与三栏考据工作台管理长程记忆。',
    },
    {
        code: '04',
        title: '分镜审校与参考生图',
        desc: '按分支隔离上下文生成分镜、自动校验一致性并单格精修渲染。',
    },
    {
        code: '05',
        title: '画布嵌字与出版导出',
        desc: '在无限画布中调整竖排/横排气泡，输出 PDF、CBZ 与条漫。',
    },
]

export default function HomePage() {
    const navigate = useNavigate()
    const [brokenCovers, setBrokenCovers] = useState<Record<string, boolean>>({})
    const { data, isLoading } = useQuery({
        queryKey: ['projects', '', 1, 8],
        queryFn: () => projectService.list(undefined, { page: 1, page_size: 8 }),
    })

    const projects = data?.items || []

    return (
        <div className="space-y-10">
            {/* Restrained Editorial Masthead */}
            <section className="pb-7 border-b flex flex-col md:flex-row md:items-end justify-between gap-6" style={{ borderColor: 'var(--border)' }}>
                <div className="space-y-2.5 max-w-2xl">
                    <div className="font-mono text-[11px] uppercase tracking-widest" style={{ color: 'var(--accent)' }}>
                        MANGAFORGE EDITORIAL STUDIO
                    </div>
                    <h1 className="font-editorial text-3xl font-bold tracking-tight leading-snug m-0" style={{ color: 'var(--text-primary)' }}>
                        长篇连载漫画的知识图谱、分镜编辑与续画工作台
                    </h1>
                    <p className="text-xs leading-relaxed m-0" style={{ color: 'var(--text-secondary)' }}>
                        围绕人物命运演进、伏笔跨话闭环与参考图一致渲染构建的专业创作环境。选择下方连载进入章节目录、人物星图、伏笔时间线或漫画画布。
                    </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                    <Button theme="light" icon={<IconBook size={14} />} onClick={() => navigate('/projects')}>
                        全部作品 ({data?.total ?? 0})
                    </Button>
                    <Button theme="solid" icon={<IconPlus size={14} />} onClick={() => navigate('/projects?create=1')}>
                        新建连载工程
                    </Button>
                </div>
            </section>

            {/* Recent Works Editorial Gallery */}
            <section className="space-y-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-xs font-semibold uppercase tracking-wider m-0" style={{ color: 'var(--text-muted)' }}>
                        最近编辑的连载作品
                    </h2>
                    <button
                        type="button"
                        onClick={() => navigate('/projects')}
                        className="text-xs bg-transparent border-0 cursor-pointer hover:underline"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        进入作品库 →
                    </button>
                </div>

                {isLoading ? (
                    <div className="py-12 flex justify-center">
                        <Spin />
                    </div>
                ) : projects.length === 0 ? (
                    <div className="py-14 border rounded-md text-center space-y-3" style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-panel)' }}>
                        <div className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                            尚无连载工程
                        </div>
                        <Button size="small" theme="solid" onClick={() => navigate('/projects?create=1')}>
                            创建第一部作品
                        </Button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {projects.map((p) => {
                            const mainPlot = p.canon_rules?.story_bible?.main_plot
                            const epTotal = p.episode_count ?? 0
                            const epDone = p.understood_count ?? 0
                            return (
                                <div
                                    key={p.id}
                                    onClick={() => navigate(`/projects/${p.id}?view=episodes`)}
                                    className="rounded-md border p-4 flex gap-4 cursor-pointer transition-colors hover:border-[var(--accent)]"
                                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                                >
                                    <div
                                        className="w-20 h-28 rounded-[4px] border overflow-hidden shrink-0"
                                        style={{ backgroundColor: 'var(--bg-elevated)', borderColor: 'var(--border)' }}
                                    >
                                        {p.cover_image_path && !brokenCovers[p.id] ? (
                                            <img
                                                src={storageFileUrl(p.cover_image_path)}
                                                alt={p.title}
                                                onError={() =>
                                                    setBrokenCovers((prev) => ({ ...prev, [p.id]: true }))
                                                }
                                                className="w-full h-full object-cover object-top"
                                            />
                                        ) : (
                                            <div
                                                className="w-full h-full flex items-center justify-center font-editorial text-xs p-2 text-center"
                                                style={{ color: 'var(--text-primary)' }}
                                            >
                                                {p.title.slice(0, 6)}
                                            </div>
                                        )}
                                    </div>

                                    <div className="min-w-0 flex-1 flex flex-col justify-between">
                                        <div className="space-y-1">
                                            <div className="flex items-center justify-between gap-2">
                                                <h3 className="font-editorial text-base font-bold m-0 truncate" style={{ color: 'var(--text-primary)' }}>
                                                    {p.title}
                                                </h3>
                                                <span className="font-mono text-[10px] shrink-0" style={{ color: 'var(--text-muted)' }}>
                                                    {epDone}/{epTotal} 话
                                                </span>
                                            </div>
                                            <p className="text-xs m-0 line-clamp-2 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                                {mainPlot?.current_arc || p.description || '点击进入章节目录与设定工作台'}
                                            </p>
                                        </div>

                                        {/* Quick Direct Workspace Jumps */}
                                        <div
                                            className="flex flex-wrap items-center gap-3 pt-2 border-t text-[11px]"
                                            style={{ borderColor: 'var(--border-subtle)' }}
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            <button
                                                type="button"
                                                onClick={() => navigate(`/projects/${p.id}?view=characters`)}
                                                className="bg-transparent border-0 p-0 cursor-pointer flex items-center gap-1 hover:text-[var(--accent)]"
                                                style={{ color: 'var(--text-secondary)' }}
                                            >
                                                <IconGraph size={12} /> 人物图谱
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => navigate(`/projects/${p.id}?view=pits`)}
                                                className="bg-transparent border-0 p-0 cursor-pointer flex items-center gap-1 hover:text-[var(--accent)]"
                                                style={{ color: 'var(--text-secondary)' }}
                                            >
                                                <IconTimeline size={12} /> 伏笔轨道
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => navigate(`/projects/${p.id}?view=qa`)}
                                                className="bg-transparent border-0 p-0 cursor-pointer flex items-center gap-1 hover:text-[var(--accent)]"
                                                style={{ color: 'var(--text-secondary)' }}
                                            >
                                                <IconResearch size={12} /> 剧情考据
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* Hairline 5-Stage Editorial Pipeline Strip (no card soup) */}
            <section className="pt-6 border-t space-y-4" style={{ borderColor: 'var(--border)' }}>
                <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                    创作流水线
                </div>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
                    {WORKFLOW_STAGES.map((s) => (
                        <div key={s.code} className="space-y-1.5">
                            <div className="font-mono text-[11px] font-semibold" style={{ color: 'var(--accent)' }}>
                                {s.code}
                            </div>
                            <div className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                                {s.title}
                            </div>
                            <p className="text-xs leading-relaxed m-0" style={{ color: 'var(--text-muted)' }}>
                                {s.desc}
                            </p>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    )
}
