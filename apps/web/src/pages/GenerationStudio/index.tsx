import { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
    Spin,
    Empty,
    Button,
    Select,
    TextArea,
    Steps,
    Toast,
    Tag,
    Input,
    Image,
    Modal,
    Banner,
} from '@douyinfe/semi-ui'
import { IconForward, IconArrowLeft, IconSearch, IconBolt, IconRefresh } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    assetService,
    episodeService,
    generationService,
    memoryService,
    pitService,
    storageFileUrl,
} from '@/services/project'
import type {
    GenerationRun,
    GeneratedImage,
    ComposedPage,
    Storyboard,
    GenerationContext,
} from '@/services/project'
import BubbleCanvasEditor from '@/components/BubbleCanvasEditor'

const LAYOUT_OPTIONS = [
    { value: 'splash', label: 'Splash 单幅整页特写 (1格)' },
    { value: '2_cinematic', label: '双格宽银幕分镜 (2格)' },
    { value: '2_vertical', label: '上下双格对切 (2格)' },
    { value: '3_panels', label: '经典上1下2日漫分格 (3格)' },
    { value: '3_vertical', label: '三段纵向叙事 (3格)' },
    { value: '2x2', label: '标准四格分镜 (4格)' },
    { value: '4_manga_dynamic', label: '动态不对称四格 (4格)' },
    { value: '5_panels', label: '快节奏五格蒙太奇 (5格)' },
]

export default function GenerationStudio() {
    const { projectId, episodeId } = useParams<{ projectId: string; episodeId: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const [tone, setTone] = useState('main')
    const [customInstructions, setCustomInstructions] = useState('')
    const [manualStep, setManualStep] = useState<number | null>(null)

    const [imageBackend, setImageBackend] = useState<string | undefined>(undefined)
    const [imageModel, setImageModel] = useState<string | undefined>(undefined)
    const [imageSize, setImageSize] = useState<string>('1024x1024')

    const [editedStoryboard, setEditedStoryboard] = useState<Storyboard | null>(null)
    const [writingMode, setWritingMode] = useState<'horizontal' | 'vertical'>('vertical')

    // Single-panel rerender modal state
    const [rerenderPanelId, setRerenderPanelId] = useState<string | null>(null)
    const [rerenderPrompt, setRerenderPrompt] = useState('')
    const [rerenderNegPrompt, setRerenderNegPrompt] = useState('')
    const [rerenderRefIds, setRerenderRefIds] = useState<string[]>([])
    const [rerenderBackend, setRerenderBackend] = useState<string | undefined>(undefined)

    const [showContextModal, setShowContextModal] = useState(false)
    const [previewContext, setPreviewContext] = useState<GenerationContext | null>(null)
    const [contextLoading, setContextLoading] = useState(false)

    const prevActiveRunsRef = useRef(0)

    const { data: episode, isLoading: episodeLoading } = useQuery({
        queryKey: ['episode', episodeId],
        queryFn: () => episodeService.get(episodeId!),
        enabled: !!episodeId,
    })

    const { data: memories } = useQuery({
        queryKey: ['episode-memories', episodeId],
        queryFn: () => episodeService.getMemories(episodeId!),
        enabled: !!episodeId,
    })

    const { data: runs } = useQuery({
        queryKey: ['generation-runs', episodeId],
        queryFn: () => generationService.listEpisodeRuns(episodeId!),
        enabled: !!episodeId,
        refetchInterval: (query) => {
            const items = query.state.data?.items || []
            const anyActive = items.some((r: GenerationRun) => r.status === 'queued' || r.status === 'running')
            return anyActive ? 2500 : false
        },
    })

    const { data: generatedImagesData } = useQuery({
        queryKey: ['generated-images', episodeId, 'all'],
        queryFn: () => generationService.getGeneratedImages(episodeId!, true),
        enabled: !!episodeId,
    })

    const { data: layoutResult } = useQuery({
        queryKey: ['layout-result', episodeId],
        queryFn: () => generationService.getLayoutResult(episodeId!),
        enabled: !!episodeId,
    })

    const { data: projectAssets } = useQuery({
        queryKey: ['project-assets-studio', projectId],
        queryFn: () => assetService.list(projectId!, undefined, { page: 1, page_size: 100 }),
        enabled: !!projectId,
    })

    const { data: openPitsData } = useQuery({
        queryKey: ['project-open-pits-studio', projectId],
        queryFn: () => pitService.list(projectId!, 'open', { page: 1, page_size: 30 }),
        enabled: !!projectId,
    })

    const storyboardMemories = memories?.filter((m) => m.type === 'storyboard_json') || []
    const storyboardMemory = storyboardMemories[storyboardMemories.length - 1]
    const serverStoryboard = useMemo(
        () => (storyboardMemory?.content ? structuredClone(storyboardMemory.content as unknown as Storyboard) : null),
        [storyboardMemory],
    )
    const draftStoryboard = editedStoryboard ?? serverStoryboard
    const storyboardDirty = editedStoryboard !== null
    const setDraftStoryboard = (sb: Storyboard) => setEditedStoryboard(sb)

    // Auto-invalidate dependent queries when background tasks run or complete (external queryClient sync only)
    useEffect(() => {
        const items = runs?.items || []
        const activeList = items.filter((r) => r.status === 'queued' || r.status === 'running')

        if (activeList.length > 0) {
            queryClient.invalidateQueries({ queryKey: ['episode-memories', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['generated-images', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['layout-result', episodeId] })
        } else if (prevActiveRunsRef.current > 0 && activeList.length === 0) {
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['episode-memories', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['generated-images', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['layout-result', episodeId] })
        }
        prevActiveRunsRef.current = activeList.length
    }, [runs, episodeId, queryClient])

    const computedStep = useMemo(() => {
        const activeList = (runs?.items || []).filter((r) => r.status === 'queued' || r.status === 'running')
        const stages = new Set(activeList.map((r) => r.stage))
        if (stages.has('writeback') || stages.has('layout')) return 3
        if (stages.has('render')) return 2
        if (stages.has('script')) return 0
        if ((layoutResult?.pages || []).length > 0 || episode?.status === 'published') return 3
        if ((generatedImagesData?.items || []).length > 0 || episode?.status === 'rendered') return 2
        if (storyboardMemory || episode?.status === 'scripted') return 1
        return 0
    }, [runs, layoutResult, generatedImagesData, storyboardMemory, episode])

    const activeStep = manualStep ?? computedStep
    const setActiveStep = (s: number) => setManualStep(s)

    const baseEpNumber = Math.max(0.01, (episode?.number || 2) - 0.01)

    const loadContextPreview = async () => {
        if (!projectId || !episode) return
        setShowContextModal(true)
        setContextLoading(true)
        try {
            const ctx = await memoryService.getGenerationContext(projectId, episode.branch_id, baseEpNumber)
            setPreviewContext(ctx)
        } finally {
            setContextLoading(false)
        }
    }

    const scriptMutation = useMutation({
        mutationFn: () =>
            generationService.triggerScriptGeneration({
                episode_id: episodeId!,
                branch_id: episode?.branch_id || '',
                base_episode_number: Math.floor((episode?.number || 2) - 0.01),
                tone,
                custom_instructions: customInstructions || undefined,
            }),
        onSuccess: () => {
            setEditedStoryboard(null)
            setManualStep(null)
            Toast.success('分镜脚本生成与一致性审校已启动')
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const saveStoryboardMutation = useMutation({
        mutationFn: (sb: Storyboard) => generationService.updateStoryboard(episodeId!, sb),
        onSuccess: () => {
            setEditedStoryboard(null)
            queryClient.invalidateQueries({ queryKey: ['episode-memories', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
            Toast.success('分镜脚本修改已保存')
        },
        onError: () => {},
    })

    const renderMutation = useMutation({
        mutationFn: async () => {
            if (storyboardDirty && draftStoryboard) {
                await generationService.updateStoryboard(episodeId!, draftStoryboard)
                setEditedStoryboard(null)
            }
            return generationService.triggerRender({
                episode_id: episodeId!,
                image_backend: imageBackend || undefined,
                image_model: imageModel || undefined,
                image_size: imageSize,
            })
        },
        onSuccess: () => {
            Toast.success('Render Agent 已开始检索角色参考图并逐格生图')
            setManualStep(2)
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const layoutMutation = useMutation({
        mutationFn: async (overrideMode?: 'horizontal' | 'vertical') => {
            if (storyboardDirty && draftStoryboard) {
                await generationService.updateStoryboard(episodeId!, draftStoryboard)
                setEditedStoryboard(null)
            }
            return generationService.triggerLayout({
                episode_id: episodeId!,
                writing_mode: overrideMode || writingMode,
                sync: true,
            })
        },
        onSuccess: () => {
            Toast.success('漫画页面分格与对白气泡已实时合成')
            setManualStep(3)
            queryClient.invalidateQueries({ queryKey: ['layout-result', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
        },
        onError: () => {},
    })

    const rerenderPanelMutation = useMutation({
        mutationFn: async () => {
            if (!rerenderPanelId) throw new Error('No panel selected')
            return generationService.rerenderPanel(episodeId!, rerenderPanelId, {
                prompt: rerenderPrompt || undefined,
                negative_prompt: rerenderNegPrompt || undefined,
                reference_asset_ids: rerenderRefIds.length > 0 ? rerenderRefIds : undefined,
                image_backend: rerenderBackend || imageBackend || undefined,
                image_model: imageModel || undefined,
                image_size: imageSize,
            })
        },
        onSuccess: () => {
            Toast.success(`Panel ${rerenderPanelId} 单格重绘完成，已自动保留历史候选版本`)
            setRerenderPanelId(null)
            queryClient.invalidateQueries({ queryKey: ['generated-images', episodeId] })
            queryClient.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
        },
        onError: () => {},
    })

    const selectCandidateMutation = useMutation({
        mutationFn: ({ panelId, imageId }: { panelId: string; imageId: string }) =>
            generationService.selectPanelCandidate(episodeId!, panelId, imageId),
        onSuccess: () => {
            Toast.success('已切换该分格的生效候选原画')
            queryClient.invalidateQueries({ queryKey: ['generated-images', episodeId] })
        },
        onError: () => {},
    })

    const continueMutation = useMutation({
        mutationFn: () =>
            generationService.triggerContinue({
                project_id: projectId!,
                branch_id: episode?.branch_id || '',
                base_episode_number: episode?.number || 1,
            }),
        onSuccess: (data) => {
            Toast.success('下一话全流程续画已启动')
            setManualStep(null)
            navigate(`/projects/${projectId}/episodes/${data.episode_id}/generate`)
        },
        onError: () => {},
    })

    const candidatesByPanel = useMemo(() => {
        const items = generatedImagesData?.items || []
        const map = new Map<string, GeneratedImage[]>()
        for (const img of items) {
            const key = img.panel_id || img.id
            const arr = map.get(key) || []
            arr.push(img)
            map.set(key, arr)
        }
        return map
    }, [generatedImagesData])
    const generatedImages: GeneratedImage[] = useMemo(() => {
        const active: GeneratedImage[] = []
        candidatesByPanel.forEach((list) => {
            const picked = list.find((i) => Boolean(i.meta?.selected)) || list[list.length - 1]
            if (picked) active.push(picked)
        })
        return active
    }, [candidatesByPanel])

    if (episodeLoading) {
        return (
            <div className="py-20 flex justify-center">
                <Spin size="large" />
            </div>
        )
    }
    if (!episode) return <Empty description="章节不存在" />

    const runList = runs?.items || []
    const activeRuns = runList.filter((r) => r.status === 'queued' || r.status === 'running')
    const isScriptRunning = activeRuns.some((r) => r.stage === 'script')
    const isRenderRunning = activeRuns.some((r) => r.stage === 'render')
    const isLayoutRunning = activeRuns.some((r) => r.stage === 'layout' || r.stage === 'writeback')
    const isContinueRunning = activeRuns.some((r) => r.stage === 'continue')

    const composedPages: ComposedPage[] = layoutResult?.pages || []

    const studioAssets = projectAssets?.items || []
    const characterChips = studioAssets.filter((a) => a.type === 'character').slice(0, 12)
    const openPitChips = (openPitsData?.items || []).slice(0, 8)

    const openPanelRerender = (img: GeneratedImage) => {
        const pid = img.panel_id || ''
        setRerenderPanelId(pid)
        const sbPanel = draftStoryboard?.pages
            .flatMap((p) => p.panels)
            .find((p) => p.panel_id === pid)
        setRerenderPrompt(String(img.meta?.prompt || sbPanel?.prompt || ''))
        setRerenderNegPrompt(String(img.meta?.negative_prompt || sbPanel?.negative_prompt || ''))
        const metaIds = Array.isArray(img.meta?.reference_asset_ids)
            ? (img.meta?.reference_asset_ids as string[])
            : []
        setRerenderRefIds(metaIds)
        setRerenderBackend(imageBackend)
    }

    const handleBubbleApplyAndRecompose = async (nextSb: Storyboard, mode: 'horizontal' | 'vertical') => {
        setWritingMode(mode)
        await generationService.updateStoryboard(episodeId!, nextSb)
        setEditedStoryboard(null)
        await layoutMutation.mutateAsync(mode)
    }

    return (
        <div className="space-y-6">
            {/* Top Studio Bar */}
            <div className="studio-card p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1">
                    <div className="flex items-center gap-2">
                        <Button
                            size="small"
                            theme="borderless"
                            icon={<IconArrowLeft />}
                            onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}`)}
                        >
                            返回本话阅读页
                        </Button>
                    </div>
                    <h1 className="text-xl font-extrabold text-slate-900 m-0">
                        AI 漫画分镜与渲染工坊 · 第 {episode.label || episode.number} 话
                    </h1>
                </div>

                <div className="flex flex-wrap gap-2">
                    <Button icon={<IconSearch />} onClick={loadContextPreview}>
                        预览将传入 LLM 的上下文记忆
                    </Button>
                    {composedPages.length > 0 && (
                        <Button
                            theme="solid"
                            onClick={() =>
                                window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                            }
                        >
                            导出成稿 PDF
                        </Button>
                    )}
                </div>
            </div>

            {(isContinueRunning || activeRuns.length > 0) && (
                <Banner
                    type="info"
                    closeIcon={null}
                    description={`流水线正在运行中：${activeRuns.map((r) => `${r.stage} (${r.status})`).join(' · ')}，完成后页面会自动更新。`}
                />
            )}

            <div className="studio-card p-6 space-y-6">
                <Steps
                    type="basic"
                    current={activeStep}
                    onChange={(idx) => setActiveStep(idx)}
                >
                    <Steps.Step title="1. 剧情策划与生成" description="组装记忆生成分镜" />
                    <Steps.Step title="2. 分镜脚本审阅编辑" description="可逐格调整台词与 Prompt" />
                    <Steps.Step title="3. 角色一致生图" description="Agent 挂载参考图渲染" />
                    <Steps.Step title="4. 分格气泡排版与回写" description="合成最终页并写回记忆" />
                </Steps>

                {/* STEP 0: CONFIGURE & GENERATE SCRIPT */}
                {activeStep === 0 && (
                    <div className="max-w-2xl space-y-5 pt-2">
                        <div>
                            <label className="block text-sm font-semibold mb-1.5">本话叙事基调</label>
                            <Select value={tone} onChange={(v) => setTone(String(v || 'main'))} style={{ width: '100%' }}>
                                <Select.Option value="main">主线推进 (承接上话结尾并推进核心矛盾)</Select.Option>
                                <Select.Option value="pit_resolve">伏笔揭秘与回收 (优先兑现高优未解伏笔)</Select.Option>
                                <Select.Option value="climax">戏剧高潮与转折 (大跨页张力与关键冲突)</Select.Option>
                                <Select.Option value="daily">日常互动与人物塑造 (强化性格口癖与关系)</Select.Option>
                                <Select.Option value="filler">独立支线短章</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-sm font-semibold mb-1.5">导演剧情指令（可选）</label>
                            {(characterChips.length > 0 || openPitChips.length > 0) && (
                                <div className="mb-2 space-y-1.5 bg-slate-50 rounded-xl p-2.5 border border-slate-200">
                                    {characterChips.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            <span className="text-[11px] font-semibold text-slate-500">点击插入 @角色：</span>
                                            {characterChips.map((ch) => (
                                                <button
                                                    key={ch.id}
                                                    type="button"
                                                    onClick={() =>
                                                        setCustomInstructions((prev) =>
                                                            prev ? `${prev} @${ch.name}` : `聚焦 @${ch.name} `,
                                                        )
                                                    }
                                                    className="inline-flex items-center gap-1 text-[11px] bg-white hover:bg-indigo-50 text-indigo-800 border border-indigo-200 rounded-full px-2 py-0.5 cursor-pointer transition"
                                                >
                                                    {ch.preview_image_path && (
                                                        <img
                                                            src={storageFileUrl(ch.preview_image_path)}
                                                            alt={ch.name}
                                                            className="w-3.5 h-3.5 rounded-full object-cover"
                                                        />
                                                    )}
                                                    @{ch.name}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    {openPitChips.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            <span className="text-[11px] font-semibold text-slate-500">点击回收 #伏笔：</span>
                                            {openPitChips.map((pit) => (
                                                <button
                                                    key={pit.id}
                                                    type="button"
                                                    onClick={() =>
                                                        setCustomInstructions((prev) =>
                                                            prev
                                                                ? `${prev}\n请在本话推进/回收伏笔【${pit.title}】`
                                                                : `请在本话推进/回收伏笔【${pit.title}】`,
                                                        )
                                                    }
                                                    className="text-[11px] bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-200 rounded-full px-2 py-0.5 cursor-pointer transition"
                                                >
                                                    #{pit.title.slice(0, 18)}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                            <TextArea
                                value={customInstructions}
                                onChange={setCustomInstructions}
                                placeholder="例如：本话开头紧接上一话发光的信件，揭示爷爷年轻时的约定，并出现关键新道具..."
                                rows={4}
                            />
                        </div>
                        <div className="flex flex-wrap gap-3">
                            <Button
                                theme="solid"
                                size="large"
                                icon={<IconBolt />}
                                loading={scriptMutation.isPending || isScriptRunning}
                                disabled={isScriptRunning}
                                onClick={() => scriptMutation.mutate()}
                            >
                                {isScriptRunning ? '正在创作并审校分镜脚本...' : draftStoryboard ? '重新生成分镜脚本' : '生成分镜脚本'}
                            </Button>
                            {draftStoryboard && (
                                <Button size="large" onClick={() => setActiveStep(1)}>
                                    查看已有分镜脚本 →
                                </Button>
                            )}
                        </div>
                    </div>
                )}

                {/* STEP 1: INTERACTIVE STORYBOARD EDITOR */}
                {activeStep === 1 && (
                    <div className="space-y-5 pt-2">
                        {!draftStoryboard ? (
                            <Empty description="尚未生成分镜脚本，请先在第一步点击「生成分镜脚本」。" />
                        ) : (
                            <>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50 rounded-xl p-4 border border-slate-200">
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-600 mb-1">本话标题</label>
                                        <Input
                                            value={draftStoryboard.title}
                                            onChange={(val) => {
                                                setDraftStoryboard({ ...draftStoryboard, title: val })
                                            }}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-600 mb-1">本话主线衔接说明</label>
                                        <Input
                                            value={draftStoryboard.arc_connection || ''}
                                            onChange={(val) => {
                                                setDraftStoryboard({ ...draftStoryboard, arc_connection: val })
                                            }}
                                        />
                                    </div>
                                    <div className="md:col-span-2">
                                        <label className="block text-xs font-semibold text-slate-600 mb-1">剧情大纲 (Synopsis)</label>
                                        <TextArea
                                            rows={2}
                                            value={draftStoryboard.synopsis}
                                            onChange={(val) => {
                                                setDraftStoryboard({ ...draftStoryboard, synopsis: val })
                                            }}
                                        />
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    {draftStoryboard.pages.map((page, pIdx) => (
                                        <div key={pIdx} className="border border-slate-200 rounded-xl p-4 space-y-4 bg-white">
                                            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
                                                <span className="font-bold text-slate-900">
                                                    第 {page.page_number} 页 ({page.panels.length} 格)
                                                </span>
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs text-slate-500">分格模板：</span>
                                                    <Select
                                                        size="small"
                                                        value={page.layout}
                                                        style={{ width: 230 }}
                                                        onChange={(v) => {
                                                            const next = structuredClone(draftStoryboard)
                                                            next.pages[pIdx].layout = String(v)
                                                            setDraftStoryboard(next)
                                                        }}
                                                    >
                                                        {LAYOUT_OPTIONS.map((opt) => (
                                                            <Select.Option key={opt.value} value={opt.value}>
                                                                {opt.label}
                                                            </Select.Option>
                                                        ))}
                                                    </Select>
                                                </div>
                                            </div>

                                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                                {page.panels.map((panel, panIdx) => (
                                                    <div
                                                        key={panIdx}
                                                        className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-2.5"
                                                    >
                                                        <div className="flex items-center justify-between">
                                                            <Tag color="indigo">Panel {panel.panel_id}</Tag>
                                                            <span className="text-xs text-slate-500">景别：{panel.camera}</span>
                                                        </div>
                                                        <div>
                                                            <label className="block text-[11px] text-slate-500 mb-0.5">画面动作与场景</label>
                                                            <Input
                                                                size="small"
                                                                value={panel.scene}
                                                                onChange={(val) => {
                                                                    const next = structuredClone(draftStoryboard)
                                                                    next.pages[pIdx].panels[panIdx].scene = val
                                                                    setDraftStoryboard(next)
                                                                }}
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="block text-[11px] text-slate-500 mb-0.5">英文生图 Prompt</label>
                                                            <TextArea
                                                                rows={2}
                                                                value={panel.prompt}
                                                                onChange={(val) => {
                                                                    const next = structuredClone(draftStoryboard)
                                                                    next.pages[pIdx].panels[panIdx].prompt = val
                                                                    setDraftStoryboard(next)
                                                                }}
                                                            />
                                                        </div>
                                                        {panel.dialogue.length > 0 && (
                                                            <div className="space-y-1.5 pt-1">
                                                                <div className="text-[11px] text-slate-500">对白与旁白气泡</div>
                                                                {panel.dialogue.map((dlg, dIdx) => (
                                                                    <div key={dIdx} className="flex gap-1.5">
                                                                        <Input
                                                                            size="small"
                                                                            style={{ width: 96 }}
                                                                            placeholder="说话人"
                                                                            value={dlg.speaker}
                                                                            onChange={(val) => {
                                                                                const next = structuredClone(draftStoryboard)
                                                                                next.pages[pIdx].panels[panIdx].dialogue[dIdx].speaker = val
                                                                                setDraftStoryboard(next)
                                                                            }}
                                                                        />
                                                                        <Input
                                                                            size="small"
                                                                            value={dlg.text}
                                                                            onChange={(val) => {
                                                                                const next = structuredClone(draftStoryboard)
                                                                                next.pages[pIdx].panels[panIdx].dialogue[dIdx].text = val
                                                                                setDraftStoryboard(next)
                                                                            }}
                                                                        />
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                                    <Button onClick={() => setActiveStep(0)}>← 返回重写分镜</Button>
                                    <div className="flex gap-2">
                                        {storyboardDirty && (
                                            <Button
                                                loading={saveStoryboardMutation.isPending}
                                                onClick={() => saveStoryboardMutation.mutate(draftStoryboard)}
                                            >
                                                保存分镜修改
                                            </Button>
                                        )}
                                        <Button theme="solid" onClick={() => setActiveStep(2)}>
                                            确认分镜，下一步渲染原画 →
                                        </Button>
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {/* STEP 2: RENDER PANEL IMAGES */}
                {activeStep === 2 && (
                    <div className="space-y-5 pt-2">
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-slate-50 rounded-xl p-4 border border-slate-200 items-end">
                            <div>
                                <label className="block text-xs font-semibold text-slate-600 mb-1">图像后端</label>
                                <Select
                                    value={imageBackend}
                                    onChange={(v) => setImageBackend(v ? String(v) : undefined)}
                                    style={{ width: '100%' }}
                                    placeholder="使用系统默认"
                                >
                                    <Select.Option value="antigravity">Antigravity (原生生图)</Select.Option>
                                    <Select.Option value="openai">OpenAI (GPT-Image)</Select.Option>
                                    <Select.Option value="gemini">Gemini (Nano Banana)</Select.Option>
                                    <Select.Option value="comfyui">ComfyUI (本地工作流)</Select.Option>
                                    <Select.Option value="custom">Custom HTTP</Select.Option>
                                    <Select.Option value="mock">Mock 本地打样</Select.Option>
                                </Select>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-slate-600 mb-1">模型覆盖</label>
                                <Select
                                    value={imageModel}
                                    onChange={(v) => setImageModel(v ? String(v) : undefined)}
                                    style={{ width: '100%' }}
                                    placeholder="使用默认模型"
                                >
                                    <Select.Option value="gpt-image-2">gpt-image-2</Select.Option>
                                    <Select.Option value="gemini-3.1-flash-image">gemini-3.1-flash-image</Select.Option>
                                    <Select.Option value="gemini-3-pro-image">gemini-3-pro-image</Select.Option>
                                </Select>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-slate-600 mb-1">分格尺寸</label>
                                <Select
                                    value={imageSize}
                                    onChange={(v) => setImageSize(String(v || '1024x1024'))}
                                    style={{ width: '100%' }}
                                >
                                    <Select.Option value="1024x1024">1024x1024</Select.Option>
                                    <Select.Option value="1024x1536">1024x1536</Select.Option>
                                    <Select.Option value="1536x1024">1536x1024</Select.Option>
                                </Select>
                            </div>
                            <Button
                                theme="solid"
                                icon={<IconBolt />}
                                loading={renderMutation.isPending || isRenderRunning}
                                disabled={isRenderRunning}
                                onClick={() => renderMutation.mutate()}
                            >
                                {isRenderRunning ? 'Render Agent 生图中...' : generatedImages.length > 0 ? '重新渲染全部分格' : '启动一致性渲染'}
                            </Button>
                        </div>

                        {isRenderRunning && (
                            <div className="py-10 text-center space-y-2">
                                <Spin size="large" />
                                <div className="text-sm text-slate-600">
                                    Render Agent 正在检索角色设定图与画风基准并逐格生成画面（已完成 {generatedImages.length} 格）...
                                </div>
                            </div>
                        )}

                        {generatedImages.length > 0 && (
                            <div className="space-y-4">
                                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                    {generatedImages.map((img) => {
                                        const pid = img.panel_id || img.id
                                        const candidates = candidatesByPanel.get(pid) || [img]
                                        const refNames = Array.isArray(img.meta?.reference_assets)
                                            ? (img.meta?.reference_assets as string[])
                                            : []
                                        return (
                                            <div key={img.id} className="border border-slate-200 rounded-xl p-2.5 bg-white space-y-2 flex flex-col">
                                                <div className="flex items-center justify-between">
                                                    <Tag size="small" color="indigo">
                                                        Panel {pid}
                                                    </Tag>
                                                    <Button
                                                        size="small"
                                                        theme="borderless"
                                                        icon={<IconRefresh />}
                                                        onClick={() => openPanelRerender(img)}
                                                    >
                                                        单格重绘
                                                    </Button>
                                                </div>
                                                <Image
                                                    src={storageFileUrl(img.image_path)}
                                                    alt={`Panel ${pid}`}
                                                    className="w-full rounded"
                                                />
                                                {refNames.length > 0 && (
                                                    <div className="flex flex-wrap gap-1">
                                                        {refNames.slice(0, 3).map((rn, idx) => (
                                                            <span key={idx} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                                                                ref: {rn}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}
                                                {candidates.length > 1 && (
                                                    <div className="pt-1 border-t border-slate-100 space-y-1">
                                                        <div className="text-[10px] text-slate-500 font-semibold">
                                                            候选版本切换 ({candidates.length})
                                                        </div>
                                                        <div className="flex flex-wrap gap-1">
                                                            {candidates.map((cand, cIdx) => {
                                                                const isCur = cand.id === img.id
                                                                return (
                                                                    <button
                                                                        key={cand.id}
                                                                        type="button"
                                                                        disabled={selectCandidateMutation.isPending}
                                                                        onClick={() =>
                                                                            !isCur &&
                                                                            selectCandidateMutation.mutate({
                                                                                panelId: pid,
                                                                                imageId: cand.id,
                                                                            })
                                                                        }
                                                                        className={`px-1.5 py-0.5 rounded text-[10px] border cursor-pointer ${
                                                                            isCur
                                                                                ? 'bg-indigo-600 text-white border-indigo-600 font-bold'
                                                                                : 'bg-slate-50 text-slate-600 border-slate-200 hover:border-indigo-400'
                                                                        }`}
                                                                    >
                                                                        v{cIdx + 1}
                                                                    </button>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                                <div className="flex justify-between pt-2">
                                    <Button onClick={() => setActiveStep(1)}>← 返回调整分镜或对白</Button>
                                    <Button
                                        theme="solid"
                                        size="large"
                                        loading={layoutMutation.isPending}
                                        onClick={() => layoutMutation.mutate(writingMode)}
                                    >
                                        合成漫画排版与对白气泡 →
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* STEP 3: INTERACTIVE BUBBLE STUDIO & WRITEBACK */}
                {activeStep === 3 && (
                    <div className="space-y-5 pt-2">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="text-sm text-slate-600">
                                支持传统日漫竖排与横排气泡切换、鼠标拖拽调整气泡位置、切换呐喊/低语样式，以及导出 PDF / CBZ / 长条漫。
                            </div>
                            <div className="flex gap-2">
                                <Button
                                    loading={layoutMutation.isPending || isLayoutRunning}
                                    onClick={() => layoutMutation.mutate(writingMode)}
                                >
                                    {composedPages.length > 0 ? '重新合成全部页' : '开始合成漫画页'}
                                </Button>
                                {composedPages.length > 0 && (
                                    <Button
                                        theme="solid"
                                        icon={<IconForward />}
                                        loading={continueMutation.isPending}
                                        onClick={() => continueMutation.mutate()}
                                    >
                                        继续续画下一话
                                    </Button>
                                )}
                            </div>
                        </div>

                        {isLayoutRunning && (
                            <div className="py-10 text-center space-y-2">
                                <Spin size="large" />
                                <div className="text-sm text-slate-600">正在执行漫画分格排版与记忆闭环回写...</div>
                            </div>
                        )}

                        {composedPages.length > 0 && (
                            <BubbleCanvasEditor
                                episodeId={episodeId!}
                                pages={composedPages}
                                storyboard={draftStoryboard}
                                writingMode={writingMode}
                                onWritingModeChange={setWritingMode}
                                onApplyAndRecompose={handleBubbleApplyAndRecompose}
                                recomposing={layoutMutation.isPending}
                            />
                        )}
                    </div>
                )}
            </div>

            {/* SINGLE PANEL RERENDER MODAL */}
            <Modal
                title={`单格精修重绘 · Panel ${rerenderPanelId || ''}`}
                visible={Boolean(rerenderPanelId)}
                onCancel={() => setRerenderPanelId(null)}
                okText="立即重绘此格（保留旧版候选）"
                confirmLoading={rerenderPanelMutation.isPending}
                onOk={() => rerenderPanelMutation.mutate()}
                width={680}
            >
                <div className="space-y-3.5 text-xs">
                    <div>
                        <label className="block font-semibold text-slate-700 mb-1">本格生图 Prompt</label>
                        <TextArea rows={4} value={rerenderPrompt} onChange={setRerenderPrompt} />
                    </div>
                    <div>
                        <label className="block font-semibold text-slate-700 mb-1">负向约束 (Negative Prompt)</label>
                        <Input
                            value={rerenderNegPrompt}
                            onChange={setRerenderNegPrompt}
                            placeholder="speech bubble, text, watermark, blurry"
                        />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                            <label className="block font-semibold text-slate-700 mb-1">显式挂载参考资产（角色/道具/场景）</label>
                            <Select
                                multiple
                                filter
                                style={{ width: '100%' }}
                                value={rerenderRefIds}
                                onChange={(vals) => setRerenderRefIds(Array.isArray(vals) ? vals.map(String) : [])}
                                placeholder="留空则按分镜角色自动匹配"
                            >
                                {studioAssets.map((a) => (
                                    <Select.Option key={a.id} value={a.id}>
                                        [{a.type}] {a.name}
                                    </Select.Option>
                                ))}
                            </Select>
                        </div>
                        <div>
                            <label className="block font-semibold text-slate-700 mb-1">生图后端</label>
                            <Select
                                style={{ width: '100%' }}
                                value={rerenderBackend}
                                onChange={(v) => setRerenderBackend(v ? String(v) : undefined)}
                                placeholder="沿用当前后端"
                            >
                                <Select.Option value="antigravity">Antigravity</Select.Option>
                                <Select.Option value="openai">OpenAI (GPT-Image)</Select.Option>
                                <Select.Option value="gemini">Gemini</Select.Option>
                                <Select.Option value="comfyui">ComfyUI (本地工作流)</Select.Option>
                                <Select.Option value="mock">Mock 打样</Select.Option>
                            </Select>
                        </div>
                    </div>
                </div>
            </Modal>

            {/* CONTEXT PREVIEW MODAL */}
            <Modal
                title={`第 ${episode.label} 话 LLM 续画上下文预览（严格截至前一话）`}
                visible={showContextModal}
                onCancel={() => setShowContextModal(false)}
                footer={null}
                width={860}
            >
                {contextLoading ? (
                    <div className="py-12 flex justify-center">
                        <Spin size="large" />
                    </div>
                ) : previewContext ? (
                    <div className="space-y-4 max-h-[70vh] overflow-y-auto text-xs pr-1">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div className="rounded-xl bg-indigo-50 p-3.5 space-y-1">
                                <div className="font-bold text-indigo-900">主线核心矛盾</div>
                                <div>{previewContext.story_bible?.main_plot?.core_conflict || '（将从历史摘要推导）'}</div>
                            </div>
                            <div className="rounded-xl bg-amber-50 p-3.5 space-y-1">
                                <div className="font-bold text-amber-900">上一话结尾无缝桥接</div>
                                <div>
                                    {previewContext.previous_bridge
                                        ? `第 ${previewContext.previous_bridge.episode_number} 话 · ${previewContext.previous_bridge.ending_state?.cliffhanger || previewContext.previous_bridge.summary}`
                                        : '暂无前置理解章节'}
                                </div>
                            </div>
                        </div>

                        <div className="rounded-xl border border-slate-200 p-3.5 space-y-1.5">
                            <div className="font-bold text-slate-900">
                                传入的角色档案与原声样本 ({previewContext.character_dossier?.length || 0})
                            </div>
                            {(previewContext.character_dossier || []).map((c) => (
                                <div key={c.id} className="bg-slate-50 rounded p-2">
                                    <span className="font-semibold text-slate-900">{c.name}</span>：{c.description}
                                    {c.current_state && <div className="text-emerald-700 mt-0.5">累积状态：{c.current_state}</div>}
                                    {c.speech_samples && c.speech_samples.length > 0 && (
                                        <div className="text-indigo-700 mt-0.5">原声台词：{c.speech_samples.join(' / ')}</div>
                                    )}
                                </div>
                            ))}
                        </div>

                        {(previewContext.unavailable_characters || []).length > 0 && (
                            <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3.5 space-y-1">
                                <div className="font-bold text-rose-900">
                                    已故 / 封印 / 失踪状态硬锁定 ({previewContext.unavailable_characters?.length})
                                </div>
                                {(previewContext.unavailable_characters || []).map((uc) => (
                                    <div key={uc.id} className="text-rose-800">
                                        • <strong>{uc.name}</strong> [{uc.vital_status.toUpperCase()}
                                        {uc.vital_status_episode ? ` · 第${uc.vital_status_episode}话` : ''}]
                                        {uc.vital_status_note ? `：${uc.vital_status_note}` : ''}
                                    </div>
                                ))}
                            </div>
                        )}

                        <div className="rounded-xl border border-slate-200 p-3.5 space-y-1">
                            <div className="font-bold text-slate-900">活跃待填伏笔 ({previewContext.active_pits.length})</div>
                            {previewContext.active_pits.map((p, idx) => (
                                <div key={idx}>
                                    • [{p.priority_label || p.priority}] {p.description}
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <Empty description="暂无上下文" />
                )}
            </Modal>
        </div>
    )
}
