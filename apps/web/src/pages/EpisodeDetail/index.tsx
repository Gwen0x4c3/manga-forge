import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
    Spin,
    Empty,
    Tag,
    Tabs,
    TabPane,
    Button,
    Collapse,
    Toast,
    Modal,
    Select,
    TextArea,
    RadioGroup,
    Image,
} from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconBolt, IconForward, IconArrowLeft, IconRefresh, IconEdit } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { episodeService, generationService, storageFileUrl } from '@/services/project'
import type { EpisodeMemory, GenerationRun } from '@/services/project'

const STATUS_META: Record<string, { label: string; color: TagColor }> = {
    imported: { label: '已导入 · 待理解', color: 'blue' },
    understood: { label: '已理解剧情', color: 'cyan' },
    scripted: { label: '已生成分镜', color: 'green' },
    rendered: { label: '已生成原画', color: 'orange' },
    published: { label: '已排版成稿', color: 'purple' },
    draft: { label: '续画草稿', color: 'grey' },
    generating: { label: '生成中', color: 'violet' },
}

const RUN_STAGE_LABELS: Record<string, string> = {
    understand: '多模态剧情理解',
    script: '分镜剧本创作与审校',
    render: '角色一致原画渲染',
    layout: '漫画分格与气泡排版',
    writeback: '成稿记忆闭环回写',
    continue: '全流程自动续画',
}

const RUN_STATUS_LABELS: Record<string, string> = {
    queued: '排队中',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
}

function formatRunError(error?: string | null): string {
    if (!error) return ''
    if (error.includes('OPENAI_API_KEY') || error.includes('LLM 未配置')) {
        return '大模型未配置：请在 `.env` 中配置有效的 `OPENAI_API_KEY` 后重启服务。'
    }
    if (error.includes('OPENAI_BASE_URL')) {
        return '大模型网关地址配置有误：请检查 `.env` 中的 `OPENAI_BASE_URL`。'
    }
    return error
}

export default function EpisodeDetail() {
    const { projectId, episodeId } = useParams<{ projectId: string; episodeId: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const [showContinue, setShowContinue] = useState(false)
    const [continueTone, setContinueTone] = useState('main')
    const [continueInstructions, setContinueInstructions] = useState('')
    const [readerMode, setReaderMode] = useState<'scroll' | 'grid'>('scroll')
    const [inspectRun, setInspectRun] = useState<GenerationRun | null>(null)
    const prevActiveCountRef = useRef(0)

    const { data: episode, isLoading: episodeLoading } = useQuery({
        queryKey: ['episode', episodeId],
        queryFn: () => episodeService.get(episodeId!),
        enabled: !!episodeId,
    })

    const { data: pages, isLoading: pagesLoading } = useQuery({
        queryKey: ['episode-pages', episodeId],
        queryFn: () => episodeService.getPages(episodeId!),
        enabled: !!episodeId,
    })

    const { data: memories, isLoading: memoriesLoading } = useQuery({
        queryKey: ['episode-memories', episodeId],
        queryFn: () => episodeService.getMemories(episodeId!),
        enabled: !!episodeId,
    })

    const { data: generatedImages, isLoading: imagesLoading } = useQuery({
        queryKey: ['generated-images', episodeId],
        queryFn: () => generationService.getGeneratedImages(episodeId!),
        enabled: !!episodeId,
    })

    const { data: layoutResult, isLoading: layoutLoading } = useQuery({
        queryKey: ['layout-result', episodeId],
        queryFn: () => generationService.getLayoutResult(episodeId!),
        enabled: !!episodeId,
    })

    const { data: runsData, isLoading: runsLoading } = useQuery({
        queryKey: ['generation-runs', episodeId],
        queryFn: () => generationService.listEpisodeRuns(episodeId!),
        enabled: !!episodeId,
        refetchInterval: (query) => {
            const items = query.state.data?.items || []
            const hasActive = items.some((r: GenerationRun) => r.status === 'queued' || r.status === 'running')
            return hasActive ? 2500 : false
        },
    })

    // Auto-refresh episode, memories, images, and layout whenever active tasks finish
    useEffect(() => {
        const items = runsData?.items || []
        const activeCount = items.filter((r) => r.status === 'queued' || r.status === 'running').length
        if (prevActiveCountRef.current > 0 && activeCount === 0) {
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['episode-memories', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['generated-images', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['layout-result', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['project', projectId] })
        }
        prevActiveCountRef.current = activeCount
    }, [runsData, episodeId, projectId, queryClient])

    const understandMutation = useMutation({
        mutationFn: () => generationService.triggerUnderstand(episodeId!),
        onSuccess: () => {
            Toast.success('多模态剧情理解任务已启动')
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const renderMutation = useMutation({
        mutationFn: () => generationService.triggerRender({ episode_id: episodeId! }),
        onSuccess: () => {
            Toast.success('角色一致原画渲染已启动')
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const layoutMutation = useMutation({
        mutationFn: () => generationService.triggerLayout({ episode_id: episodeId! }),
        onSuccess: () => {
            Toast.success('漫画页面排版任务已启动')
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const continueMutation = useMutation({
        mutationFn: () =>
            generationService.triggerContinue({
                project_id: projectId!,
                branch_id: episode?.branch_id || '',
                base_episode_number: episode?.number || 1,
                tone: continueTone,
                custom_instructions: continueInstructions || undefined,
            }),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowContinue(false)
            Toast.success('下一话全流程续画已启动')
            navigate(`/projects/${projectId}/episodes/${data.episode_id}/generate`)
        },
        onError: () => {},
    })

    if (episodeLoading) {
        return (
            <div className="py-20 flex justify-center">
                <Spin size="large" />
            </div>
        )
    }
    if (!episode) return <Empty description="未找到该章节" />

    const activeRuns = (runsData?.items || []).filter(
        (r: GenerationRun) => r.status === 'queued' || r.status === 'running',
    )
    const activeStages = new Set(activeRuns.map((r: GenerationRun) => r.stage))
    const latestRun = runsData?.items?.[0]

    const summaryMemories =
        memories?.filter((m: EpisodeMemory) => m.type === 'summary' && (m.content as Record<string, unknown>)?.summary) || []
    const summaryMemory = summaryMemories[summaryMemories.length - 1]
    const understanding = (summaryMemory?.content || {}) as Record<string, unknown>
    const mainPlot = (understanding.main_plot || {}) as Record<string, string>
    const endingState = (understanding.ending_state || {}) as Record<string, unknown>
    const understandingEvents = (understanding.events || []) as Array<Record<string, unknown>>
    const understandingChanges = (understanding.state_changes || []) as Array<Record<string, unknown>>
    const understandingCharacters = (understanding.characters || []) as Array<Record<string, unknown>>
    const newAssetsDiscovered = (understanding.new_assets || []) as Array<Record<string, unknown>>
    const worldRules = (understanding.world_rules_discovered || []) as string[]

    const ocrMemory = (memories?.filter((m: EpisodeMemory) => m.type === 'ocr_dump') || []).pop()
    const consistencyMemory = (memories?.filter((m: EpisodeMemory) => m.type === 'consistency_report') || []).pop()
    const storyboardMemories = memories?.filter((m: EpisodeMemory) => m.type === 'storyboard_json') || []
    const storyboardMemory = storyboardMemories[storyboardMemories.length - 1]

    const hasComposedPages = (layoutResult?.pages || []).length > 0
    const defaultTab = hasComposedPages ? 'layout' : (pages && pages.length > 0 ? 'pages' : 'summary')
    const statusInfo = STATUS_META[episode.status] || { label: episode.status, color: 'grey' as TagColor }

    return (
        <div className="space-y-6">
            {/* Header Bar */}
            <div className="studio-card p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                        <Button
                            size="small"
                            theme="borderless"
                            icon={<IconArrowLeft />}
                            onClick={() => navigate(`/projects/${projectId}`)}
                        >
                            返回项目工作台
                        </Button>
                    </div>
                    <div className="flex flex-wrap items-center gap-2.5">
                        <h1 className="text-xl font-extrabold text-slate-900 m-0">
                            第 {episode.label || episode.number} 话{episode.title ? ` · ${episode.title}` : ''}
                        </h1>
                        <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                        <Tag color={episode.source === 'generated' ? 'violet' : 'grey'}>
                            {episode.source === 'generated' ? 'AI 续画章节' : '原作导入章节'}
                        </Tag>
                    </div>
                </div>

                <div className="flex flex-wrap gap-2">
                    {pages && pages.length > 0 && (
                        <Button
                            icon={summaryMemory ? <IconRefresh /> : <IconBolt />}
                            theme={episode.status === 'imported' ? 'solid' : 'light'}
                            loading={understandMutation.isPending || activeStages.has('understand')}
                            disabled={activeStages.has('understand')}
                            onClick={() => understandMutation.mutate()}
                        >
                            {activeStages.has('understand') ? '正在理解本话...' : summaryMemory ? '重新理解本话' : '执行多模态理解'}
                        </Button>
                    )}

                    <Button
                        icon={<IconEdit />}
                        theme={episode.source === 'generated' ? 'solid' : 'light'}
                        onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}/generate`)}
                    >
                        进入分镜与创作工坊
                    </Button>

                    {storyboardMemory && (
                        <Button
                            icon={<IconBolt />}
                            loading={renderMutation.isPending || activeStages.has('render')}
                            disabled={activeStages.has('render')}
                            onClick={() => renderMutation.mutate()}
                        >
                            {activeStages.has('render') ? '原画渲染中...' : '渲染分镜图'}
                        </Button>
                    )}

                    {(generatedImages?.items || []).length > 0 && (
                        <Button
                            icon={<IconBolt />}
                            loading={layoutMutation.isPending || activeStages.has('layout')}
                            disabled={activeStages.has('layout')}
                            onClick={() => layoutMutation.mutate()}
                        >
                            {activeStages.has('layout') ? '排版合成中...' : '合成漫画页'}
                        </Button>
                    )}

                    {hasComposedPages && (
                        <Button
                            onClick={() =>
                                window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                            }
                        >
                            导出 PDF
                        </Button>
                    )}

                    {['understood', 'published'].includes(episode.status) && (
                        <Button
                            theme="solid"
                            style={{ backgroundColor: '#4f46e5', color: '#fff' }}
                            icon={<IconForward />}
                            onClick={() => setShowContinue(true)}
                        >
                            从本话续画下一话
                        </Button>
                    )}
                </div>
            </div>

            {activeRuns.length > 0 && (
                <div className="rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 flex items-center gap-3 text-sm text-indigo-900">
                    <Spin size="small" />
                    <span>
                        正在执行：{activeRuns.map((r) => RUN_STAGE_LABELS[r.stage] || r.stage).join(' / ')}（页面将自动实时刷新）
                    </span>
                </div>
            )}

            {latestRun?.status === 'failed' && activeRuns.length === 0 && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                    <div className="font-semibold text-red-800 text-sm">
                        最近一次任务失败：{RUN_STAGE_LABELS[latestRun.stage] || latestRun.stage}
                    </div>
                    <div className="mt-1 text-xs text-red-700">{formatRunError(latestRun.error)}</div>
                </div>
            )}

            <div className="studio-card p-6">
                <Tabs defaultActiveKey={defaultTab}>
                    {/* FINAL COMPOSED PAGES */}
                    {hasComposedPages && (
                        <TabPane tab={`成稿阅读 (${layoutResult?.pages?.length || 0} 页)`} itemKey="layout">
                            <div className="flex items-center justify-between mb-4 pt-2">
                                <RadioGroup
                                    type="button"
                                    value={readerMode}
                                    onChange={(e) => setReaderMode(e.target.value as 'scroll' | 'grid')}
                                    options={[
                                        { label: '沉浸条漫连读', value: 'scroll' },
                                        { label: '双栏网格预览', value: 'grid' },
                                    ]}
                                />
                                <Button
                                    theme="solid"
                                    onClick={() =>
                                        window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                                    }
                                >
                                    下载整话 PDF
                                </Button>
                            </div>

                            {layoutLoading ? (
                                <Spin />
                            ) : readerMode === 'scroll' ? (
                                <div className="manga-paper-bg rounded-2xl p-4 md:p-8 flex flex-col items-center gap-6">
                                    {(layoutResult?.pages || []).map((page) => (
                                        <div key={page.page_number} className="w-full max-w-3xl bg-white shadow-lg rounded-lg overflow-hidden border border-slate-200">
                                            <Image
                                                src={storageFileUrl(page.image_path)}
                                                alt={`第 ${page.page_number} 页`}
                                                className="w-full"
                                            />
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    {(layoutResult?.pages || []).map((page) => (
                                        <div key={page.page_number} className="border border-slate-200 rounded-xl p-3 space-y-2">
                                            <div className="flex items-center justify-between text-xs text-slate-500">
                                                <span className="font-semibold text-slate-800">第 {page.page_number} 页</span>
                                                <Tag size="small">{page.layout}</Tag>
                                            </div>
                                            <Image
                                                src={storageFileUrl(page.image_path)}
                                                alt={`Page ${page.page_number}`}
                                                className="w-full"
                                            />
                                        </div>
                                    ))}
                                </div>
                            )}
                        </TabPane>
                    )}

                    {/* ORIGINAL IMPORTED PAGES */}
                    <TabPane tab={`原作画面 (${pages?.length || 0})`} itemKey="pages">
                        {pagesLoading && <Spin />}
                        {!pagesLoading && (!pages || pages.length === 0) && (
                            <Empty description={episode.source === 'generated' ? '本话为 AI 续画章节，请查看「分镜脚本」「分镜原画」或「成稿阅读」标签页' : '暂未上传漫画页面'} />
                        )}
                        {!pagesLoading && pages && pages.length > 0 && (
                            <div className="space-y-4 pt-2">
                                <div className="flex justify-start">
                                    <RadioGroup
                                        type="button"
                                        value={readerMode}
                                        onChange={(e) => setReaderMode(e.target.value as 'scroll' | 'grid')}
                                        options={[
                                            { label: '沉浸连读模式', value: 'scroll' },
                                            { label: '缩略网格模式', value: 'grid' },
                                        ]}
                                    />
                                </div>
                                {readerMode === 'scroll' ? (
                                    <div className="manga-paper-bg rounded-2xl p-4 md:p-8 flex flex-col items-center gap-5">
                                        {pages.map((page) => (
                                            <div key={page.id} className="w-full max-w-2xl bg-white shadow rounded-lg overflow-hidden border border-slate-200">
                                                <Image
                                                    src={storageFileUrl(page.image_path)}
                                                    alt={`第 ${page.page_index + 1} 页`}
                                                    className="w-full"
                                                />
                                                <div className="text-center text-xs text-slate-400 py-1.5 bg-slate-50">
                                                    第 {page.page_index + 1} 页
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                                        {pages.map((page) => (
                                            <div key={page.id} className="border border-slate-200 rounded-xl p-2 bg-white">
                                                <div className="w-full h-72 overflow-hidden flex items-center justify-center bg-slate-50 rounded-lg">
                                                    <Image
                                                        src={storageFileUrl(page.image_path)}
                                                        alt={`Page ${page.page_index + 1}`}
                                                        className="max-w-full max-h-full object-contain"
                                                    />
                                                </div>
                                                <div className="text-center text-xs text-slate-500 mt-1.5">
                                                    第 {page.page_index + 1} 页
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </TabPane>

                    {/* EPISODE INTELLIGENCE: SUMMARY + MAIN PLOT + ENDING BRIDGE + EVENTS + STATE CHANGES */}
                    <TabPane tab="剧情与主线解析" itemKey="summary">
                        {memoriesLoading ? (
                            <Spin />
                        ) : !summaryMemory ? (
                            <Empty description="尚未生成剧情解析。请点击右上角「执行多模态理解」。" />
                        ) : (
                            <div className="space-y-6 pt-3 max-w-5xl">
                                <div className="rounded-xl bg-slate-50 border border-slate-200 p-5 space-y-2">
                                    <div className="text-xs font-bold text-indigo-600 uppercase">本话梗概 (Synopsis)</div>
                                    <p className="text-sm text-slate-800 leading-relaxed m-0">
                                        {String(understanding.summary || '')}
                                    </p>
                                </div>

                                {(mainPlot.core_conflict || mainPlot.arc_progress || Boolean(endingState.cliffhanger)) && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div className="rounded-xl border border-indigo-100 bg-indigo-50/50 p-4 space-y-2">
                                            <div className="text-xs font-bold text-indigo-800">本话主线推进</div>
                                            {mainPlot.current_arc && (
                                                <div className="text-xs text-slate-700">
                                                    <span className="font-semibold">所属篇章：</span>
                                                    {mainPlot.current_arc}
                                                </div>
                                            )}
                                            {mainPlot.arc_progress && (
                                                <div className="text-xs text-slate-700 leading-relaxed">
                                                    <span className="font-semibold">关键进展：</span>
                                                    {mainPlot.arc_progress}
                                                </div>
                                            )}
                                            {mainPlot.next_hook && (
                                                <div className="text-xs text-indigo-900 leading-relaxed">
                                                    <span className="font-semibold">下话钩子：</span>
                                                    {mainPlot.next_hook}
                                                </div>
                                            )}
                                        </div>

                                        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 space-y-2">
                                            <div className="text-xs font-bold text-amber-900">结尾现场桥接 (Ending Bridge)</div>
                                            {Boolean(endingState.location) && (
                                                <div className="text-xs text-slate-700">
                                                    <span className="font-semibold">落幕地点：</span>
                                                    {String(endingState.location)}
                                                </div>
                                            )}
                                            {Array.isArray(endingState.active_characters) && endingState.active_characters.length > 0 && (
                                                <div className="text-xs text-slate-700">
                                                    <span className="font-semibold">在场人物：</span>
                                                    {(endingState.active_characters as string[]).join('、')}
                                                </div>
                                            )}
                                            {Boolean(endingState.cliffhanger) && (
                                                <div className="text-xs text-amber-950 leading-relaxed">
                                                    <span className="font-semibold">定格悬念：</span>
                                                    {String(endingState.cliffhanger)}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {understandingEvents.length > 0 && (
                                    <div className="space-y-2.5">
                                        <h3 className="text-sm font-bold text-slate-900 m-0">关键剧情时间线 ({understandingEvents.length})</h3>
                                        <div className="space-y-2">
                                            {understandingEvents.map((event, i) => (
                                                <div key={i} className="rounded-xl border border-slate-200 bg-white p-3.5 space-y-1.5">
                                                    <div className="flex items-center gap-2 flex-wrap">
                                                        <span className="text-xs font-mono text-slate-400">#{i + 1}</span>
                                                        {event.significance && event.significance !== 'normal' ? (
                                                            <Tag
                                                                size="small"
                                                                color={event.significance === 'cliffhanger' ? 'red' : 'orange'}
                                                            >
                                                                {String(event.significance)}
                                                            </Tag>
                                                        ) : null}
                                                        {Boolean(event.location) && (
                                                            <Tag size="small" color="green">
                                                                场景：{String(event.location)}
                                                            </Tag>
                                                        )}
                                                        {Array.isArray(event.characters_involved) &&
                                                            (event.characters_involved as string[]).map((c, j) => (
                                                                <Tag key={j} size="small" color="blue">
                                                                    {c}
                                                                </Tag>
                                                            ))}
                                                    </div>
                                                    <div className="text-sm text-slate-800">{String(event.description || '')}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {understandingChanges.length > 0 && (
                                    <div className="space-y-2.5">
                                        <h3 className="text-sm font-bold text-slate-900 m-0">人物与物品状态变更 ({understandingChanges.length})</h3>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                                            {understandingChanges.map((change, i) => (
                                                <div key={i} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs space-y-1">
                                                    <div className="flex items-center gap-2">
                                                        <Tag color="blue" size="small">
                                                            {String(change.character || '')}
                                                        </Tag>
                                                        <Tag size="small">{String(change.attribute || '')}</Tag>
                                                    </div>
                                                    <div className="text-slate-700">
                                                        <span className="text-slate-400">{String(change.before || '初始')}</span>
                                                        <span className="mx-1.5 text-indigo-500 font-bold">→</span>
                                                        <span className="font-semibold text-slate-900">{String(change.after || '')}</span>
                                                    </div>
                                                    {Boolean(change.reason) && (
                                                        <div className="text-slate-400">原因：{String(change.reason)}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {worldRules.length > 0 && (
                                    <div className="space-y-2">
                                        <h3 className="text-sm font-bold text-slate-900 m-0">本话揭示的世界观细节</h3>
                                        <div className="space-y-1.5">
                                            {worldRules.map((r, i) => (
                                                <div key={i} className="text-xs text-slate-700 bg-slate-50 rounded-lg px-3 py-2 border border-slate-200">
                                                    • {r}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </TabPane>

                    {/* CHARACTERS & ITEMS RECOGNIZED */}
                    <TabPane tab={`登场人物与资产 (${understandingCharacters.length + newAssetsDiscovered.length})`} itemKey="characters">
                        <div className="space-y-6 pt-3 max-w-5xl">
                            <div className="space-y-2.5">
                                <h3 className="text-sm font-bold text-slate-900 m-0">登场人物识别记录</h3>
                                {understandingCharacters.length === 0 ? (
                                    <Empty description="暂无人物识别记录" />
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        {understandingCharacters.map((c, i) => (
                                            <div key={i} className="border border-slate-200 rounded-xl p-4 space-y-2">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <span className="font-bold text-slate-900">{String(c.name || '')}</span>
                                                    {Boolean(c.role) && (
                                                        <Tag size="small" color="cyan">
                                                            {String(c.role)}
                                                        </Tag>
                                                    )}
                                                    {c.asset_id ? (
                                                        <Tag size="small" color="green">
                                                            已关联资产库
                                                        </Tag>
                                                    ) : (
                                                        <Tag size="small" color="orange">
                                                            本话新面孔
                                                        </Tag>
                                                    )}
                                                </div>
                                                {Boolean(c.appearance) && (
                                                    <div className="text-xs text-slate-600 leading-relaxed">
                                                        外貌服饰：{String(c.appearance)}
                                                    </div>
                                                )}
                                                {Boolean(c.speech_style) && (
                                                    <div className="text-xs text-indigo-700 bg-indigo-50/70 rounded px-2.5 py-1">
                                                        说话语气：{String(c.speech_style)}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {newAssetsDiscovered.length > 0 && (
                                <div className="space-y-2.5">
                                    <h3 className="text-sm font-bold text-slate-900 m-0">本话新发现物品 / 场景 / 角色资产</h3>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        {newAssetsDiscovered.map((na, idx) => (
                                            <div key={idx} className="border border-slate-200 rounded-xl p-3.5 bg-slate-50 space-y-1.5">
                                                <div className="flex items-center gap-2">
                                                    <Tag size="small" color="indigo">
                                                        {String(na.asset_type || 'item')}
                                                    </Tag>
                                                    <span className="font-semibold text-sm text-slate-900">{String(na.name || '')}</span>
                                                </div>
                                                <div className="text-xs text-slate-600 leading-relaxed">{String(na.description || '')}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </TabPane>

                    {/* DIALOGUE OCR */}
                    <TabPane tab="逐页台词转录" itemKey="dialogue">
                        {!ocrMemory ? (
                            <Empty description="暂无对白转录" />
                        ) : (
                            <div className="max-w-3xl space-y-3 pt-3">
                                {Array.isArray((ocrMemory.content as Record<string, unknown>)?.pages) ? (
                                    ((ocrMemory.content as Record<string, unknown>).pages as Array<Record<string, unknown>>).map(
                                        (page, i) => (
                                            <div key={i} className="border border-slate-200 rounded-xl p-4 space-y-1.5">
                                                <div className="font-bold text-xs text-slate-500">
                                                    第 {String(page.page_number || i + 1)} 页
                                                </div>
                                                {Array.isArray(page.lines) &&
                                                    (page.lines as Array<Record<string, unknown>>).map((line, j) => (
                                                        <div key={j} className="text-sm flex items-start gap-2">
                                                            <Tag
                                                                size="small"
                                                                color={line.line_type === 'narration' ? 'grey' : 'blue'}
                                                            >
                                                                {String(line.speaker || line.line_type || '旁白')}
                                                            </Tag>
                                                            <span className="text-slate-800">{String(line.text || '')}</span>
                                                        </div>
                                                    ))}
                                            </div>
                                        ),
                                    )
                                ) : (
                                    <pre className="text-xs bg-slate-50 p-4 rounded-xl whitespace-pre-wrap">
                                        {String((ocrMemory.content as Record<string, unknown>)?.text || '')}
                                    </pre>
                                )}
                            </div>
                        )}
                    </TabPane>

                    {/* STORYBOARD & CONSISTENCY */}
                    <TabPane tab="分镜脚本与审校" itemKey="storyboard">
                        <div className="space-y-6 pt-3 max-w-5xl">
                            {consistencyMemory && (() => {
                                const report = consistencyMemory.content as Record<string, unknown>
                                const issues = (report.issues || []) as Array<Record<string, unknown>>
                                const overall = String(report.overall || 'pass')
                                return (
                                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-bold text-slate-900">连续性编辑审校报告：</span>
                                            <Tag color={overall === 'pass' ? 'green' : overall === 'warning' ? 'orange' : 'red'}>
                                                {overall.toUpperCase()} ({issues.length} 条建议)
                                            </Tag>
                                        </div>
                                        {issues.map((issue, idx) => (
                                            <div key={idx} className="text-xs bg-white border border-slate-200 rounded-lg p-2.5">
                                                <Tag
                                                    size="small"
                                                    color={
                                                        issue.severity === 'critical'
                                                            ? 'red'
                                                            : issue.severity === 'warning'
                                                              ? 'orange'
                                                              : 'grey'
                                                    }
                                                >
                                                    {String(issue.severity)}
                                                </Tag>{' '}
                                                <span className="font-medium">[{String(issue.category)}]</span>{' '}
                                                {String(issue.description)}
                                            </div>
                                        ))}
                                    </div>
                                )
                            })()}

                            {!storyboardMemory ? (
                                <Empty description="尚未生成分镜脚本。可前往「进入分镜与创作工坊」生成或编辑分镜。" />
                            ) : (
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h3 className="text-base font-bold text-slate-900 m-0">
                                                {String((storyboardMemory.content as Record<string, unknown>)?.title || '')}
                                            </h3>
                                            <p className="text-xs text-slate-600 m-0 mt-1">
                                                {String((storyboardMemory.content as Record<string, unknown>)?.synopsis || '')}
                                            </p>
                                        </div>
                                        <Button
                                            size="small"
                                            icon={<IconEdit />}
                                            onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}/generate`)}
                                        >
                                            在工坊中编辑分镜
                                        </Button>
                                    </div>
                                    <Collapse>
                                        {Array.isArray((storyboardMemory.content as Record<string, unknown>)?.pages) &&
                                            ((storyboardMemory.content as Record<string, unknown>).pages as Array<Record<string, unknown>>).map(
                                                (page, i) => (
                                                    <Collapse.Panel
                                                        header={`第 ${page.page_number || i + 1} 页 · 布局 ${page.layout || '2x2'}`}
                                                        itemKey={String(i)}
                                                        key={i}
                                                    >
                                                        <div className="space-y-3">
                                                            {Array.isArray(page.panels) &&
                                                                (page.panels as Array<Record<string, unknown>>).map((panel, j) => (
                                                                    <div
                                                                        key={j}
                                                                        className="border-l-4 border-indigo-400 bg-slate-50 rounded-r-lg p-3 space-y-1.5"
                                                                    >
                                                                        <div className="font-bold text-xs text-indigo-900">
                                                                            分格 {String(panel.panel_id || j + 1)} · 景别 {String(panel.camera || 'medium')}
                                                                        </div>
                                                                        <div className="text-xs text-slate-700">{String(panel.scene || '')}</div>
                                                                        {Array.isArray(panel.dialogue) &&
                                                                            (panel.dialogue as Array<Record<string, unknown>>).map((d, k) => (
                                                                                <div key={k} className="text-xs">
                                                                                    <Tag size="small" color="blue">
                                                                                        {String(d.speaker || '旁白')}
                                                                                    </Tag>{' '}
                                                                                    {String(d.text || '')}
                                                                                </div>
                                                                            ))}
                                                                        <div className="text-[11px] text-slate-400 font-mono">
                                                                            Prompt: {String(panel.prompt || '')}
                                                                        </div>
                                                                    </div>
                                                                ))}
                                                        </div>
                                                    </Collapse.Panel>
                                                ),
                                            )}
                                    </Collapse>
                                </div>
                            )}
                        </div>
                    </TabPane>

                    {/* GENERATED PANEL IMAGES */}
                    <TabPane tab={`分镜原画 (${generatedImages?.items?.length || 0})`} itemKey="generated">
                        {imagesLoading ? (
                            <Spin />
                        ) : !generatedImages?.items || generatedImages.items.length === 0 ? (
                            <Empty description="暂无已渲染分镜原画" />
                        ) : (
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 pt-3">
                                {generatedImages.items.map((img) => {
                                    const refs = (img.meta?.reference_assets as string[] | undefined) || []
                                    return (
                                        <div key={img.id} className="border border-slate-200 rounded-xl p-2.5 space-y-2">
                                            <div className="w-full h-64 overflow-hidden flex items-center justify-center bg-slate-50 rounded-lg">
                                                <Image
                                                    src={storageFileUrl(img.image_path)}
                                                    alt={img.panel_id || ''}
                                                    className="max-w-full max-h-full object-contain"
                                                />
                                            </div>
                                            <div className="flex items-center justify-between text-xs">
                                                <span className="font-bold text-slate-800">Panel {img.panel_id || '-'}</span>
                                                {refs.length > 0 && (
                                                    <Tag size="small" color="green">
                                                        锚定: {refs.join(', ')}
                                                    </Tag>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </TabPane>

                    {/* TASK LOGS + LLM CONTEXT INSPECTOR */}
                    <TabPane tab={`任务日志与上下文透视 (${runsData?.items?.length || 0})`} itemKey="runs">
                        {runsLoading ? (
                            <Spin />
                        ) : !runsData?.items || runsData.items.length === 0 ? (
                            <Empty description="暂无执行记录" />
                        ) : (
                            <div className="space-y-3 pt-3">
                                {runsData.items.map((run: GenerationRun) => (
                                    <div key={run.id} className="border border-slate-200 rounded-xl p-4 space-y-2">
                                        <div className="flex items-center gap-2.5 flex-wrap">
                                            <Tag
                                                color={
                                                    run.status === 'succeeded'
                                                        ? 'green'
                                                        : run.status === 'failed'
                                                          ? 'red'
                                                          : run.status === 'running'
                                                            ? 'blue'
                                                            : 'orange'
                                                }
                                            >
                                                {RUN_STATUS_LABELS[run.status] || run.status}
                                            </Tag>
                                            <span className="font-semibold text-sm text-slate-900">
                                                {RUN_STAGE_LABELS[run.stage] || run.stage}
                                            </span>
                                            {run.model && <Tag size="small">{run.model}</Tag>}
                                            {run.retrieved_context && (
                                                <Button size="small" theme="light" onClick={() => setInspectRun(run)}>
                                                    查看传入 LLM 的完整上下文
                                                </Button>
                                            )}
                                            <span className="text-xs text-slate-400 ml-auto">
                                                {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                                            </span>
                                        </div>
                                        {run.error && (
                                            <div className="bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">
                                                {formatRunError(run.error)}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </TabPane>
                </Tabs>
            </div>

            {/* CONTINUE MODAL */}
            <Modal
                title={`从第 ${episode.label} 话向后续画新章节`}
                visible={showContinue}
                onCancel={() => setShowContinue(false)}
                footer={null}
                width={480}
            >
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">叙事模式</label>
                        <Select
                            value={continueTone}
                            onChange={(v) => setContinueTone(String(v || 'main'))}
                            style={{ width: '100%' }}
                        >
                            <Select.Option value="main">主线推进</Select.Option>
                            <Select.Option value="pit_resolve">伏笔揭秘与回收</Select.Option>
                            <Select.Option value="climax">高潮冲突</Select.Option>
                            <Select.Option value="daily">日常羁绊</Select.Option>
                        </Select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">导演附加指令（可选）</label>
                        <TextArea
                            value={continueInstructions}
                            onChange={(v) => setContinueInstructions(v)}
                            placeholder="输入本话希望发生的具体事件或人物互动..."
                            rows={3}
                        />
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowContinue(false)}>取消</Button>
                        <Button
                            theme="solid"
                            icon={<IconForward />}
                            loading={continueMutation.isPending}
                            onClick={() => continueMutation.mutate()}
                        >
                            启动下一话创作
                        </Button>
                    </div>
                </div>
            </Modal>

            {/* LLM CONTEXT INSPECTOR MODAL */}
            <Modal
                title="LLM 续画上下文载荷透视 (Retrieved Continuity Context)"
                visible={!!inspectRun}
                onCancel={() => setInspectRun(null)}
                footer={null}
                width={860}
            >
                {inspectRun?.retrieved_context && (
                    <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1 text-xs">
                        {inspectRun.retrieved_context.story_bible?.main_plot && (
                            <div className="rounded-xl bg-indigo-50 p-3.5 space-y-1">
                                <div className="font-bold text-indigo-900">1. 主线脉络 (Main Plot)</div>
                                <div>核心矛盾：{inspectRun.retrieved_context.story_bible.main_plot.core_conflict}</div>
                                <div>当前篇章：{inspectRun.retrieved_context.story_bible.main_plot.current_arc}</div>
                                <div>下话钩子：{inspectRun.retrieved_context.story_bible.main_plot.next_hook}</div>
                            </div>
                        )}
                        {inspectRun.retrieved_context.previous_bridge && (
                            <div className="rounded-xl bg-amber-50 p-3.5 space-y-1">
                                <div className="font-bold text-amber-900">
                                    2. 上一话结尾无缝桥接 (第 {inspectRun.retrieved_context.previous_bridge.episode_number} 话)
                                </div>
                                <div>结尾悬念：{inspectRun.retrieved_context.previous_bridge.ending_state?.cliffhanger}</div>
                                {inspectRun.retrieved_context.previous_bridge.closing_dialogue && (
                                    <div>
                                        末尾台词：{inspectRun.retrieved_context.previous_bridge.closing_dialogue.join(' / ')}
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-1">
                            <div className="font-bold text-slate-900">
                                3. 角色累积状态与原声样本 ({inspectRun.retrieved_context.character_dossier?.length || 0} 人)
                            </div>
                            {(inspectRun.retrieved_context.character_dossier || []).map((c, idx) => (
                                <div key={idx} className="border-b border-slate-100 py-1">
                                    <span className="font-semibold">{c.name}</span>：{c.current_state || '常规状态'}
                                    {c.speech_samples && c.speech_samples.length > 0 && (
                                        <span className="text-indigo-600 ml-2">台词样本：{c.speech_samples.join(' | ')}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                        <div className="rounded-xl bg-slate-900 text-slate-100 p-4 font-mono overflow-x-auto">
                            <pre className="m-0 whitespace-pre-wrap">
                                {JSON.stringify(inspectRun.retrieved_context, null, 2)}
                            </pre>
                        </div>
                    </div>
                )}
            </Modal>
        </div>
    )
}
