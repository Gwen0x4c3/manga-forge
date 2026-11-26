import { useNavigate } from 'react-router-dom'
import { Button, Tag, Spin } from '@douyinfe/semi-ui'
import { IconPlus, IconFolder, IconForward, IconBolt } from '@douyinfe/semi-icons'
import { useQuery } from '@tanstack/react-query'
import { projectService } from '@/services/project'

const PIPELINE_STEPS = [
    {
        step: '01',
        title: '连载导入与解析',
        desc: '支持本地图片、ZIP 压缩包或 MangaDex 整部连载抓取，自动维护话数与平行分支。',
        badge: 'ZIP / 图片 / MangaDex',
    },
    {
        step: '02',
        title: '多模态剧情与视觉识别',
        desc: '直接阅读原画页面，提取逐页台词、关键角色/物品/场景资产，并自动裁切参考图锚点。',
        badge: '人脸匹配 · 自动截框',
    },
    {
        step: '03',
        title: '主线脉络与伏笔生命周期',
        desc: '动态维护核心矛盾、当前篇章、结尾悬念桥接，追踪伏笔“埋设 → 线索推进 → 回收”闭环。',
        badge: '三层记忆 + 语义检索',
    },
    {
        step: '04',
        title: '高可靠分镜脚本与审校',
        desc: '注入角色累积状态与原声台词样本生成新分镜，经过连续性编辑审校自动修正逻辑冲突。',
        badge: '严格防剧透上下文',
    },
    {
        step: '05',
        title: '参考图一致生图与漫画排版',
        desc: 'Render Agent 自动挂载角色设定图与原作画风参考，合成专业漫画分格、对白气泡并导出 PDF。',
        badge: '多后端渲染 + 回写',
    },
]

const LANG_MAP: Record<string, string> = {
    zh: '中文连载',
    ja: '日漫原版',
    en: '英文连载',
}

export default function HomePage() {
    const navigate = useNavigate()
    const { data, isLoading } = useQuery({
        queryKey: ['projects', '', 1, 6],
        queryFn: () => projectService.list(undefined, { page: 1, page_size: 6 }),
    })

    const projects = data?.items || []

    return (
        <div className="space-y-8">
            <section className="relative overflow-hidden rounded-3xl pop-hero-surface p-8 md:p-11">
                <div className="relative z-10 max-w-3xl space-y-4">
                    <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-gradient-to-r from-orange-50 to-rose-50 border border-orange-200/80 text-[#ff4d36] text-xs font-bold tracking-wide">
                        <IconBolt size="small" />
                        MANGAFORGE STUDIO · AI 连载漫画图谱与续画工作台
                    </div>
                    <h1 className="text-3xl md:text-4xl font-black tracking-tight leading-tight text-slate-900 m-0">
                        读懂整部连载的人物命运与伏笔，
                        <br />
                        <span className="bg-gradient-to-r from-[#ff5a36] via-[#ff2e63] to-[#2563eb] bg-clip-text text-transparent">
                            创作真正忠于原作的下一话漫画
                        </span>
                    </h1>
                    <p className="text-slate-600 text-sm md:text-base leading-relaxed m-0 max-w-2xl">
                        从原画多模态理解、视觉参考图自动裁剪、角色生死与状态跨话迭代，到交互式故事宇宙图谱、单格精修渲染与传统日漫竖排嵌字，让每一话续作都保持饱满的原作灵魂。
                    </p>
                    <div className="pt-2 flex flex-wrap gap-3">
                        <Button
                            size="large"
                            theme="solid"
                            className="brand-gradient-btn"
                            icon={<IconPlus />}
                            onClick={() => navigate('/projects?create=1')}
                        >
                            新建连载漫画项目
                        </Button>
                        <Button
                            size="large"
                            theme="light"
                            icon={<IconFolder />}
                            onClick={() => navigate('/projects')}
                        >
                            浏览全部作品 ({data?.total ?? 0})
                        </Button>
                    </div>
                </div>
            </section>

            <section className="space-y-3">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-bold text-slate-900 m-0">五步全闭环续画架构</h2>
                    <span className="text-xs text-slate-500">支持按序批量理解全书 · 支持任意章节平行世界线 Fork</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
                    {PIPELINE_STEPS.map((s) => (
                        <div key={s.step} className="studio-card p-5 flex flex-col justify-between space-y-3">
                            <div className="space-y-2">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-indigo-50 text-indigo-600">
                                        STEP {s.step}
                                    </span>
                                </div>
                                <div className="font-bold text-slate-900 text-sm">{s.title}</div>
                                <p className="text-xs text-slate-500 leading-relaxed m-0">{s.desc}</p>
                            </div>
                            <div className="pt-2 border-t border-slate-100">
                                <span className="text-[11px] font-medium text-indigo-600">{s.badge}</span>
                            </div>
                        </div>
                    ))}
                </div>
            </section>

            <section className="space-y-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-bold text-slate-900 m-0">最近活跃的连载工程</h2>
                    <Button theme="borderless" icon={<IconForward />} iconPosition="right" onClick={() => navigate('/projects')}>
                        查看全部作品
                    </Button>
                </div>

                {isLoading ? (
                    <div className="py-10 flex justify-center">
                        <Spin size="large" />
                    </div>
                ) : projects.length === 0 ? (
                    <div className="studio-card p-10 text-center space-y-3">
                        <div className="text-base font-semibold text-slate-700">还没有创建连载作品</div>
                        <p className="text-sm text-slate-500 m-0">
                            创建一个新项目，上传几话漫画图片或通过 MangaDex 导入，即可体验自动剧情理解与续画。
                        </p>
                        <div className="pt-2">
                            <Button theme="solid" icon={<IconPlus />} onClick={() => navigate('/projects?create=1')}>
                                立即创建第一部作品
                            </Button>
                        </div>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {projects.map((p) => {
                            const mainPlot = p.canon_rules?.story_bible?.main_plot
                            return (
                                <div
                                    key={p.id}
                                    onClick={() => navigate(`/projects/${p.id}`)}
                                    className="studio-card studio-card-hover p-5 cursor-pointer flex flex-col justify-between space-y-4"
                                >
                                    <div className="space-y-2">
                                        <div className="flex items-start justify-between gap-2">
                                            <h3 className="text-base font-bold text-slate-900 m-0 line-clamp-1">{p.title}</h3>
                                            <Tag color="indigo" size="small">
                                                {LANG_MAP[p.language] || p.language.toUpperCase()}
                                            </Tag>
                                        </div>
                                        <p className="text-xs text-slate-500 line-clamp-2 m-0">
                                            {p.description || '暂无作品简介'}
                                        </p>
                                        {mainPlot?.core_conflict ? (
                                            <div className="rounded-lg bg-indigo-50/70 border border-indigo-100 p-2.5 text-xs text-indigo-950">
                                                <span className="font-semibold text-indigo-700">主线脉络：</span>
                                                <span className="line-clamp-2">{mainPlot.core_conflict}</span>
                                            </div>
                                        ) : p.long_summary ? (
                                            <div className="rounded-lg bg-slate-50 border border-slate-100 p-2.5 text-xs text-slate-600 line-clamp-2">
                                                {p.long_summary}
                                            </div>
                                        ) : null}
                                    </div>
                                    <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-100">
                                        <span>更新于 {new Date(p.updated_at).toLocaleDateString()}</span>
                                        <span className="text-indigo-600 font-medium">进入创作台 →</span>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>
        </div>
    )
}
