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
import { IconBolt, IconForward, IconArrowLeft, IconRefresh, IconEdit, IconImage } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { assetService, episodeService, generationService, storageFileUrl } from '@/services/project'
import type { EpisodeMemory, EpisodePage, GenerationRun } from '@/services/project'
import PageCropModal from '@/components/PageCropModal'

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
    const [readerMode, setReaderMode] = useState<'scroll' | 'spread' | 'grid'>('scroll')
    const [spreadIndex, setSpreadIndex] = useState(0)
    const [activeTab, setActiveTab] = useState<string | null>(null)
    const [cropPage, setCropPage] = useState<EpisodePage | null>(null)
    const [inspectRun, setInspectRun] = useState<GenerationRun | null>(null)
    const prevActiveCountRef = useRef(0)

    const { data: projectAssets } = useQuery({
        queryKey: ['project-assets-reader', projectId],
        queryFn: () => assetService.list(projectId!, undefined, { page: 1, page_size: 120 }),
        enabled: !!projectId,
    })

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

    const hasComposedPages = (layoutResult?.pages || []).length > 0
    const defaultTab = hasComposedPages ? 'layout' : (pages && pages.length > 0 ? 'pages' : 'summary')
    const currentTab = activeTab ?? defaultTab
    const activeSpreadPageCount =
        currentTab === 'layout' ? (layoutResult?.pages?.length || 0) : (pages?.length || 0)
    const totalSpreads = Math.max(1, Math.ceil(activeSpreadPageCount / 2))

    useEffect(() => {
        if (readerMode !== 'spread') return
        if (currentTab !== 'layout' && currentTab !== 'pages') return
        if (showContinue || Boolean(cropPage) || Boolean(inspectRun)) return
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
            const target = e.target as HTMLElement | null
            if (target) {
                const isTextInput =
                    target.tagName === 'TEXTAREA' ||
                    target.tagName === 'SELECT' ||
                    target.isContentEditable ||
                    (target.tagName === 'INPUT' &&
                        !['radio', 'checkbox', 'button', 'submit'].includes((target as HTMLInputElement).type))
                if (isTextInput) return
            }
            // Capture-phase intercept so focused Semi-UI RadioGroup doesn't hijack Left/Right arrows
            e.preventDefault()
            e.stopPropagation()
            if (e.key === 'ArrowLeft') {
                // RTL Japanese manga: Left Arrow flips to NEXT spread
                setSpreadIndex((s) => Math.min(totalSpreads - 1, s + 1))
            } else if (e.key === 'ArrowRight') {
                // RTL Japanese manga: Right Arrow flips to PREVIOUS spread
                setSpreadIndex((s) => Math.max(0, s - 1))
            }
        }
        window.addEventListener('keydown', onKeyDown, true)
        return () => window.removeEventListener('keydown', onKeyDown, true)
    }, [readerMode, currentTab, totalSpreads, showContinue, cropPage, inspectRun])

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
    const statusInfo = STATUS_META[episode.status] || { label: episode.status, color: 'grey' as TagColor }

    return (
        <div className="space-y-6">
            {/* Header Bar */}
            <header className="pb-4 border-b border-[var(--border)] flex flex-col lg:flex-row lg:items-center justify-between gap-4">
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
                        <h1 className="font-editorial text-xl font-bold text-[var(--text-primary)] m-0">
                            第 {episode.label || episode.number} 话{episode.title ? ` · ${episode.title}` : ''}
                        </h1>
                        <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                        <Tag color={episode.source === 'generated' ? 'violet' : 'grey'}>
                            {episode.source === 'generated' ? '续画成稿' : '原作导入'}
                        </Tag>
                    </div>
                </div>

                <div className="flex flex-wrap gap-2">
                    {pages && pages.length > 0 && (
                        <Button
                            size="small"
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
                        size="small"
                        icon={<IconEdit />}
                        theme={episode.source === 'generated' ? 'solid' : 'light'}
                        onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}/generate`)}
                    >
                        进入漫画编辑器
                    </Button>

                    {storyboardMemory && (
                        <Button
                            size="small"
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
                            size="small"
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
                            size="small"
                            onClick={() =>
                                window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                            }
                        >
                            导出 PDF
                        </Button>
                    )}

                    {['understood', 'published'].includes(episode.status) && (
                        <Button
                            size="small"
                            theme="solid"
                            icon={<IconForward />}
                            onClick={() => setShowContinue(true)}
                        >
                            从本话续画下一话
                        </Button>
                    )}
                </div>
            </header>

            {activeRuns.length > 0 && (
                <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] px-4 py-3 flex items-center gap-3 text-sm text-[var(--text-primary)]">
                    <Spin size="small" />
                    <span>
                        正在执行：{activeRuns.map((r) => RUN_STAGE_LABELS[r.stage] || r.stage).join(' / ')}（页面将自动实时刷新）
                    </span>
                </div>
            )}

            {latestRun?.status === 'failed' && activeRuns.length === 0 && (
                <div className="rounded-[6px] border border-[var(--accent)] bg-[var(--accent-soft)] p-4">
                    <div className="font-semibold text-[var(--accent)] text-sm">
                        最近一次任务失败：{RUN_STAGE_LABELS[latestRun.stage] || latestRun.stage}
                    </div>
                    <div className="mt-1 text-xs text-[var(--text-secondary)]">{formatRunError(latestRun.error)}</div>
                </div>
            )}

            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] p-5">
                <Tabs
                    activeKey={currentTab}
                    onChange={(k) => {
                        setActiveTab(k)
                        setSpreadIndex(0)
                    }}
                >
                    {/* FINAL COMPOSED PAGES */}
                    {hasComposedPages && (
                        <TabPane tab={`成稿阅读 (${layoutResult?.pages?.length || 0} 页)`} itemKey="layout">
                            <div className="flex flex-wrap items-center justify-between gap-3 mb-4 pt-2">
                                <RadioGroup
                                    type="button"
                                    value={readerMode}
                                    onChange={(e) => {
                                        setReaderMode(e.target.value as 'scroll' | 'spread' | 'grid')
                                        setSpreadIndex(0)
                                    }}
                                    options={[
                                        { label: '沉浸条漫连读', value: 'scroll' },
                                        { label: '右开双页单行本 (RTL)', value: 'spread' },
                                        { label: '双栏网格预览', value: 'grid' },
                                    ]}
                                />
                                <div className="flex flex-wrap gap-2">
                                    <Button
                                        theme="solid"
                                        onClick={() =>
                                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                                        }
                                    >
                                        下载 PDF
                                    </Button>
                                    <Button
                                        onClick={() =>
                                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=cbz`, '_blank')
                                        }
                                    >
                                        导出 CBZ
                                    </Button>
                                    <Button
                                        onClick={() =>
                                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=webtoon`, '_blank')
                                        }
                                    >
                                        导出长条漫
                                    </Button>
                                </div>
                            </div>

                            {layoutLoading ? (
                                <Spin />
                            ) : readerMode === 'scroll' ? (
                                <div className="mf-canvas-grid rounded-[6px] border border-[var(--border)] p-4 md:p-8 flex flex-col items-center gap-6">
                                    {(layoutResult?.pages || []).map((page) => (
                                        <div key={page.page_number} className="w-full max-w-3xl mf-paper-sheet rounded-[4px] overflow-hidden">
                                            <Image
                                                src={storageFileUrl(page.image_path)}
                                                alt={`第 ${page.page_number} 页`}
                                                width="100%"
                                                className="w-full mf-manga-img"
                                                imgStyle={{ width: '100%', height: 'auto', display: 'block' }}
                                            />
                                        </div>
                                    ))}
                                </div>
                            ) : readerMode === 'spread' ? (
                                (() => {
                                    const list = layoutResult?.pages || []
                                    const spreads: Array<[typeof list[number] | null, typeof list[number] | null]> = []
                                    for (let i = 0; i < list.length; i += 2) {
                                        spreads.push([list[i + 1] || null, list[i] || null])
                                    }
                                    const safeIdx = Math.min(spreadIndex, Math.max(0, spreads.length - 1))
                                    const [leftP, rightP] = spreads[safeIdx] || [null, null]
                                    return (
                                        <div className="mf-canvas-grid rounded-[6px] border border-[var(--border)] p-4 md:p-6 space-y-4">
                                            <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                                                <Button
                                                    size="small"
                                                    disabled={safeIdx >= spreads.length - 1}
                                                    onClick={() => setSpreadIndex((s) => Math.min(spreads.length - 1, s + 1))}
                                                >
                                                    ← 下一页 (左翻)
                                                </Button>
                                                <span className="font-mono font-semibold text-[var(--text-primary)]">
                                                    RTL 跨页 {safeIdx + 1} / {Math.max(1, spreads.length)}
                                                    <span className="ml-2 font-sans font-normal text-[11px] text-[var(--text-muted)]">
                                                        (支持 ← / → 键翻页)
                                                    </span>
                                                </span>
                                                <Button
                                                    size="small"
                                                    disabled={safeIdx <= 0}
                                                    onClick={() => setSpreadIndex((s) => Math.max(0, s - 1))}
                                                >
                                                    上一页 (右翻) →
                                                </Button>
                                            </div>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 max-w-5xl mx-auto">
                                                <div className="mf-paper-sheet rounded-[4px] overflow-hidden flex flex-col items-center justify-center p-1">
                                                    {leftP ? (
                                                        <img
                                                            src={storageFileUrl(leftP.image_path)}
                                                            alt={`第 ${leftP.page_number} 页`}
                                                            className="w-full max-h-[76vh] object-contain block"
                                                        />
                                                    ) : (
                                                        <span className="text-xs text-[#71717A] py-24">本话完</span>
                                                    )}
                                                </div>
                                                <div className="mf-paper-sheet rounded-[4px] overflow-hidden flex flex-col items-center justify-center p-1">
                                                    {rightP && (
                                                        <img
                                                            src={storageFileUrl(rightP.image_path)}
                                                            alt={`第 ${rightP.page_number} 页`}
                                                            className="w-full max-h-[76vh] object-contain block"
                                                        />
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    )
                                })()
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                                    {(layoutResult?.pages || []).map((page) => (
                                        <div key={page.page_number} className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[6px] p-3 space-y-2">
                                            <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
                                                <span className="font-mono font-semibold text-[var(--text-primary)]">第 {page.page_number} 页</span>
                                                <Tag size="small">{page.layout}</Tag>
                                            </div>
                                            <div className="mf-paper-sheet rounded-[4px] overflow-hidden">
                                                <Image
                                                    src={storageFileUrl(page.image_path)}
                                                    alt={`Page ${page.page_number}`}
                                                    width="100%"
                                                    className="w-full mf-manga-img"
                                                    imgStyle={{ width: '100%', height: 'auto', display: 'block' }}
                                                />
                                            </div>
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
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <RadioGroup
                                        type="button"
                                        value={readerMode}
                                        onChange={(e) => {
                                            setReaderMode(e.target.value as 'scroll' | 'spread' | 'grid')
                                            setSpreadIndex(0)
                                        }}
                                        options={[
                                            { label: '沉浸连读模式', value: 'scroll' },
                                            { label: '右开双页单行本 (RTL)', value: 'spread' },
                                            { label: '缩略网格模式', value: 'grid' },
                                        ]}
                                    />
                                    <span className="text-xs text-[var(--text-muted)]">
                                        提示：点击任意页下方的「框选裁图入库」可直接从原作截取角色/道具参考图
                                    </span>
                                </div>
                                {readerMode === 'scroll' ? (
                                    <div className="mf-canvas-grid rounded-[6px] border border-[var(--border)] p-4 md:p-8 flex flex-col items-center gap-5">
                                        {pages.map((page) => (
                                            <div key={page.id} className="w-full max-w-2xl mf-paper-sheet rounded-[4px] overflow-hidden">
                                                <Image
                                                    src={storageFileUrl(page.image_path)}
                                                    alt={`第 ${page.page_index + 1} 页`}
                                                    width="100%"
                                                    className="w-full mf-manga-img"
                                                    imgStyle={{ width: '100%', height: 'auto', display: 'block' }}
                                                />
                                                <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-elevated)] border-t border-[var(--border)] text-xs text-[var(--text-secondary)]">
                                                    <span className="font-mono">P.{String(page.page_index + 1).padStart(2, '0')}</span>
                                                    <Button
                                                        size="small"
                                                        theme="borderless"
                                                        icon={<IconImage />}
                                                        onClick={() => setCropPage(page)}
                                                    >
                                                        框选裁图入资产库
                                                    </Button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : readerMode === 'spread' ? (
                                    (() => {
                                        const spreads: Array<[EpisodePage | null, EpisodePage | null]> = []
                                        for (let i = 0; i < pages.length; i += 2) {
                                            spreads.push([pages[i + 1] || null, pages[i] || null])
                                        }
                                        const safeIdx = Math.min(spreadIndex, Math.max(0, spreads.length - 1))
                                        const [leftP, rightP] = spreads[safeIdx] || [null, null]
                                        return (
                                            <div className="mf-canvas-grid rounded-[6px] border border-[var(--border)] p-4 md:p-6 space-y-4">
                                                <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                                                    <Button
                                                        size="small"
                                                        disabled={safeIdx >= spreads.length - 1}
                                                        onClick={() => setSpreadIndex((s) => Math.min(spreads.length - 1, s + 1))}
                                                    >
                                                        ← 下一页 (左翻)
                                                    </Button>
                                                    <span className="font-mono font-semibold text-[var(--text-primary)]">
                                                        RTL 跨页 {safeIdx + 1} / {Math.max(1, spreads.length)}
                                                        <span className="ml-2 font-sans font-normal text-[11px] text-[var(--text-muted)]">
                                                            (支持 ← / → 键翻页)
                                                        </span>
                                                    </span>
                                                    <Button
                                                        size="small"
                                                        disabled={safeIdx <= 0}
                                                        onClick={() => setSpreadIndex((s) => Math.max(0, s - 1))}
                                                    >
                                                        上一页 (右翻) →
                                                    </Button>
                                                </div>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 max-w-5xl mx-auto">
                                                    {[leftP, rightP].map((pg, idx) => (
                                                        <div
                                                            key={idx}
                                                            className="mf-paper-sheet rounded-[4px] overflow-hidden flex flex-col justify-between"
                                                        >
                                                            {pg ? (
                                                                <>
                                                                    <img
                                                                        src={storageFileUrl(pg.image_path)}
                                                                        alt={`第 ${pg.page_index + 1} 页`}
                                                                        className="w-full max-h-[76vh] object-contain block"
                                                                    />
                                                                    <div className="flex items-center justify-between px-3 py-1 bg-[var(--bg-elevated)] border-t border-[var(--border)] text-[11px] text-[var(--text-secondary)]">
                                                                        <span className="font-mono">P.{String(pg.page_index + 1).padStart(2, '0')}</span>
                                                                        <Button
                                                                            size="small"
                                                                            theme="borderless"
                                                                            icon={<IconImage />}
                                                                            onClick={() => setCropPage(pg)}
                                                                        >
                                                                            框选裁图
                                                                        </Button>
                                                                    </div>
                                                                </>
                                                            ) : (
                                                                <div className="flex-1 flex items-center justify-center text-xs text-[#71717A] py-24">
                                                                    空白页
                                                                </div>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )
                                    })()
                                ) : (
                                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3.5">
                                        {pages.map((page) => (
                                            <div key={page.id} className="border border-[var(--border)] rounded-[6px] p-2 bg-[var(--bg-elevated)] space-y-1.5">
                                                <div className="w-full aspect-[3/4] overflow-hidden flex items-center justify-center mf-paper-sheet rounded-[4px] p-1">
                                                    <Image
                                                        src={storageFileUrl(page.image_path)}
                                                        alt={`Page ${page.page_index + 1}`}
                                                        className="mf-manga-thumb"
                                                        imgStyle={{ maxWidth: '100%', maxHeight: '100%', width: 'auto', height: 'auto', objectFit: 'contain' }}
                                                    />
                                                </div>
                                                <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1">
                                                    <span className="font-mono">P.{String(page.page_index + 1).padStart(2, '0')}</span>
                                                    <Button
                                                        size="small"
                                                        theme="borderless"
                                                        onClick={() => setCropPage(page)}
                                                    >
                                                        裁图
                                                    </Button>
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
                                <div className="rounded-[6px] bg-[var(--bg-elevated)] border border-[var(--border)] p-4 space-y-1.5">
                                    <div className="text-[11px] font-mono text-[var(--accent)] uppercase tracking-wider">Synopsis · 本话梗概</div>
                                    <p className="text-sm text-[var(--text-primary)] leading-relaxed m-0">
                                        {String(understanding.summary || '')}
                                    </p>
                                </div>

                                {(mainPlot.core_conflict || mainPlot.arc_progress || Boolean(endingState.cliffhanger)) && (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                                        <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-4 space-y-2">
                                            <div className="text-xs font-semibold text-[var(--text-primary)]">本话主线推进</div>
                                            {mainPlot.current_arc && (
                                                <div className="text-xs text-[var(--text-secondary)]">
                                                    <span className="font-semibold text-[var(--text-primary)]">所属篇章：</span>
                                                    {mainPlot.current_arc}
                                                </div>
                                            )}
                                            {mainPlot.arc_progress && (
                                                <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
                                                    <span className="font-semibold text-[var(--text-primary)]">关键进展：</span>
                                                    {mainPlot.arc_progress}
                                                </div>
                                            )}
                                            {mainPlot.next_hook && (
                                                <div className="text-xs text-[var(--accent)] leading-relaxed">
                                                    <span className="font-semibold">下话钩子：</span>
                                                    {mainPlot.next_hook}
                                                </div>
                                            )}
                                        </div>

                                        <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-4 space-y-2">
                                            <div className="text-xs font-semibold text-[var(--text-primary)]">结尾现场桥接 (Ending Bridge)</div>
                                            {Boolean(endingState.location) && (
                                                <div className="text-xs text-[var(--text-secondary)]">
                                                    <span className="font-semibold text-[var(--text-primary)]">落幕地点：</span>
                                                    {String(endingState.location)}
                                                </div>
                                            )}
                                            {Array.isArray(endingState.active_characters) && endingState.active_characters.length > 0 && (
                                                <div className="text-xs text-[var(--text-secondary)]">
                                                    <span className="font-semibold text-[var(--text-primary)]">在场人物：</span>
                                                    {(endingState.active_characters as string[]).join('、')}
                                                </div>
                                            )}
                                            {Boolean(endingState.cliffhanger) && (
                                                <div className="text-xs text-[var(--text-primary)] leading-relaxed">
                                                    <span className="font-semibold">定格悬念：</span>
                                                    {String(endingState.cliffhanger)}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {understandingEvents.length > 0 && (
                                    <div className="space-y-2.5">
                                        <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                            关键剧情时间线 ({understandingEvents.length})
                                        </h3>
                                        <div className="space-y-2">
                                            {understandingEvents.map((event, i) => (
                                                <div key={i} className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5 space-y-1.5">
                                                    <div className="flex items-center gap-2 flex-wrap">
                                                        <span className="text-xs font-mono text-[var(--text-muted)]">#{i + 1}</span>
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
                                                    <div className="text-sm text-[var(--text-primary)]">{String(event.description || '')}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {understandingChanges.length > 0 && (
                                    <div className="space-y-2.5">
                                        <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                            人物与物品状态变更 ({understandingChanges.length})
                                        </h3>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                                            {understandingChanges.map((change, i) => (
                                                <div key={i} className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-xs space-y-1">
                                                    <div className="flex items-center gap-2">
                                                        <Tag color="blue" size="small">
                                                            {String(change.character || '')}
                                                        </Tag>
                                                        <Tag size="small">{String(change.attribute || '')}</Tag>
                                                    </div>
                                                    <div className="text-[var(--text-secondary)]">
                                                        <span className="text-[var(--text-muted)]">{String(change.before || '初始')}</span>
                                                        <span className="mx-1.5 text-[var(--accent)] font-bold">→</span>
                                                        <span className="font-semibold text-[var(--text-primary)]">{String(change.after || '')}</span>
                                                    </div>
                                                    {Boolean(change.reason) && (
                                                        <div className="text-[var(--text-muted)]">原因：{String(change.reason)}</div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {worldRules.length > 0 && (
                                    <div className="space-y-2">
                                        <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                            本话揭示的世界观细节
                                        </h3>
                                        <div className="space-y-1.5">
                                            {worldRules.map((r, i) => (
                                                <div key={i} className="text-xs text-[var(--text-secondary)] bg-[var(--bg-elevated)] rounded-[4px] px-3 py-2 border border-[var(--border)]">
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
                                <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">登场人物识别记录</h3>
                                {understandingCharacters.length === 0 ? (
                                    <Empty description="暂无人物识别记录" />
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        {understandingCharacters.map((c, i) => (
                                            <div key={i} className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[6px] p-4 space-y-2">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <span className="font-semibold text-[var(--text-primary)]">{String(c.name || '')}</span>
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
                                                    <div className="text-xs text-[var(--text-secondary)] leading-relaxed">
                                                        外貌服饰：{String(c.appearance)}
                                                    </div>
                                                )}
                                                {Boolean(c.speech_style) && (
                                                    <div className="text-xs text-[var(--text-secondary)] bg-[var(--bg-panel)] border border-[var(--border)] rounded-[4px] px-2.5 py-1">
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
                                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                        本话新发现物品 / 场景 / 角色资产
                                    </h3>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        {newAssetsDiscovered.map((na, idx) => (
                                            <div key={idx} className="border border-[var(--border)] rounded-[6px] p-3.5 bg-[var(--bg-elevated)] space-y-1.5">
                                                <div className="flex items-center gap-2">
                                                    <Tag size="small">
                                                        {String(na.asset_type || 'item')}
                                                    </Tag>
                                                    <span className="font-semibold text-sm text-[var(--text-primary)]">{String(na.name || '')}</span>
                                                </div>
                                                <div className="text-xs text-[var(--text-secondary)] leading-relaxed">{String(na.description || '')}</div>
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
                                            <div key={i} className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[6px] p-4 space-y-1.5">
                                                <div className="font-mono font-semibold text-xs text-[var(--text-muted)]">
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
                                                            <span className="text-[var(--text-primary)]">{String(line.text || '')}</span>
                                                        </div>
                                                    ))}
                                            </div>
                                        ),
                                    )
                                ) : (
                                    <pre className="text-xs bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-secondary)] p-4 rounded-[6px] whitespace-pre-wrap">
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
                                    <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-4 space-y-2">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-semibold text-[var(--text-primary)]">连续性编辑审校报告：</span>
                                            <Tag color={overall === 'pass' ? 'green' : overall === 'warning' ? 'orange' : 'red'}>
                                                {overall.toUpperCase()} ({issues.length} 条建议)
                                            </Tag>
                                        </div>
                                        {issues.map((issue, idx) => (
                                            <div key={idx} className="text-xs bg-[var(--bg-panel)] border border-[var(--border)] rounded-[4px] p-2.5 text-[var(--text-secondary)]">
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
                                                <span className="font-medium text-[var(--text-primary)]">[{String(issue.category)}]</span>{' '}
                                                {String(issue.description)}
                                            </div>
                                        ))}
                                    </div>
                                )
                            })()}

                            {!storyboardMemory ? (
                                <Empty description="尚未生成分镜脚本。可前往「进入漫画编辑器」生成或编辑分镜。" />
                            ) : (
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h3 className="text-base font-bold text-[var(--text-primary)] m-0">
                                                {String((storyboardMemory.content as Record<string, unknown>)?.title || '')}
                                            </h3>
                                            <p className="text-xs text-[var(--text-secondary)] m-0 mt-1">
                                                {String((storyboardMemory.content as Record<string, unknown>)?.synopsis || '')}
                                            </p>
                                        </div>
                                        <Button
                                            size="small"
                                            icon={<IconEdit />}
                                            onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}/generate`)}
                                        >
                                            在编辑器中修改分镜
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
                                                                        className="border-l-2 border-l-[var(--accent)] border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[4px] p-3 space-y-1.5"
                                                                    >
                                                                        <div className="font-mono font-semibold text-xs text-[var(--text-primary)]">
                                                                            分格 {String(panel.panel_id || j + 1)} · 景别 {String(panel.camera || 'medium')}
                                                                        </div>
                                                                        <div className="text-xs text-[var(--text-secondary)]">{String(panel.scene || '')}</div>
                                                                        {Array.isArray(panel.dialogue) &&
                                                                            (panel.dialogue as Array<Record<string, unknown>>).map((d, k) => (
                                                                                <div key={k} className="text-xs text-[var(--text-primary)]">
                                                                                    <Tag size="small" color="blue">
                                                                                        {String(d.speaker || '旁白')}
                                                                                    </Tag>{' '}
                                                                                    {String(d.text || '')}
                                                                                </div>
                                                                            ))}
                                                                        <div className="text-[11px] text-[var(--text-muted)] font-mono">
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
                                        <div key={img.id} className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[6px] p-2.5 space-y-2">
                                            <div className="w-full h-64 overflow-hidden flex items-center justify-center bg-[var(--bg-canvas)] rounded-[4px] p-1">
                                                <Image
                                                    src={storageFileUrl(img.image_path)}
                                                    alt={img.panel_id || ''}
                                                    className="mf-manga-thumb"
                                                    imgStyle={{ maxWidth: '100%', maxHeight: '100%', width: 'auto', height: 'auto', objectFit: 'contain' }}
                                                />
                                            </div>
                                            <div className="flex items-center justify-between text-xs">
                                                <span className="font-mono font-semibold text-[var(--text-primary)]">Panel {img.panel_id || '-'}</span>
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
                                    <div key={run.id} className="border border-[var(--border)] bg-[var(--bg-elevated)] rounded-[6px] p-4 space-y-2">
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
                                            <span className="font-semibold text-sm text-[var(--text-primary)]">
                                                {RUN_STAGE_LABELS[run.stage] || run.stage}
                                            </span>
                                            {run.model && <Tag size="small">{run.model}</Tag>}
                                            {run.retrieved_context && (
                                                <Button size="small" theme="light" onClick={() => setInspectRun(run)}>
                                                    查看传入 LLM 的完整上下文
                                                </Button>
                                            )}
                                            <span className="text-xs font-mono text-[var(--text-muted)] ml-auto">
                                                {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                                            </span>
                                        </div>
                                        {run.error && (
                                            <div className="bg-[var(--accent-soft)] border border-[var(--accent)] rounded-[4px] p-2.5 text-xs text-[var(--accent)]">
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
                            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5 space-y-1 text-[var(--text-secondary)]">
                                <div className="font-semibold text-[var(--text-primary)]">1. 主线脉络 (Main Plot)</div>
                                <div>核心矛盾：{inspectRun.retrieved_context.story_bible.main_plot.core_conflict}</div>
                                <div>当前篇章：{inspectRun.retrieved_context.story_bible.main_plot.current_arc}</div>
                                <div>下话钩子：{inspectRun.retrieved_context.story_bible.main_plot.next_hook}</div>
                            </div>
                        )}
                        {inspectRun.retrieved_context.previous_bridge && (
                            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-elevated)] p-3.5 space-y-1 text-[var(--text-secondary)]">
                                <div className="font-semibold text-[var(--text-primary)]">
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
                        <div className="rounded-[6px] bg-[var(--bg-elevated)] border border-[var(--border)] p-3.5 space-y-1 text-[var(--text-secondary)]">
                            <div className="font-semibold text-[var(--text-primary)]">
                                3. 角色累积状态与原声样本 ({inspectRun.retrieved_context.character_dossier?.length || 0} 人)
                            </div>
                            {(inspectRun.retrieved_context.character_dossier || []).map((c, idx) => (
                                <div key={idx} className="border-b border-[var(--border)] py-1">
                                    <span className="font-semibold text-[var(--text-primary)]">{c.name}</span>：{c.current_state || '常规状态'}
                                    {c.speech_samples && c.speech_samples.length > 0 && (
                                        <span className="text-[var(--accent)] ml-2">台词样本：{c.speech_samples.join(' | ')}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                        <div className="rounded-[6px] bg-[#141417] border border-[var(--border)] text-[#E4E4E7] p-4 font-mono overflow-x-auto">
                            <pre className="m-0 whitespace-pre-wrap">
                                {JSON.stringify(inspectRun.retrieved_context, null, 2)}
                            </pre>
                        </div>
                    </div>
                )}
            </Modal>

            {/* VISUAL PAGE-TO-ASSET CROP MODAL */}
            {episodeId && (
                <PageCropModal
                    visible={Boolean(cropPage)}
                    episodeId={episodeId}
                    page={cropPage}
                    assets={projectAssets?.items || []}
                    onClose={() => setCropPage(null)}
                    onCropped={() => {
                        queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
                        queryClient.invalidateQueries({ queryKey: ['project-assets-reader', projectId] })
                    }}
                />
            )}
        </div>
    )
}
