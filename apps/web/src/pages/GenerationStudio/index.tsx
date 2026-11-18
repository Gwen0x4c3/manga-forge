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
import { IconForward, IconArrowLeft, IconSearch, IconBolt } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { episodeService, generationService, memoryService, storageFileUrl } from '@/services/project'
import type {
    GenerationRun,
    GeneratedImage,
    ComposedPage,
    Storyboard,
    GenerationContext,
} from '@/services/project'

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
        queryKey: ['generated-images', episodeId],
        queryFn: () => generationService.getGeneratedImages(episodeId!),
        enabled: !!episodeId,
    })

    const { data: layoutResult } = useQuery({
        queryKey: ['layout-result', episodeId],
        queryFn: () => generationService.getLayoutResult(episodeId!),
        enabled: !!episodeId,
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
        mutationFn: async () => {
            if (storyboardDirty && draftStoryboard) {
                await generationService.updateStoryboard(episodeId!, draftStoryboard)
                setEditedStoryboard(null)
            }
            return generationService.triggerLayout({ episode_id: episodeId! })
        },
        onSuccess: () => {
            Toast.success('漫画页面分格与对白气泡排版已启动')
            setManualStep(3)
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
            }),
        onSuccess: (data) => {
            Toast.success('下一话全流程续画已启动')
            setManualStep(null)
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
    if (!episode) return <Empty description="章节不存在" />

    const runList = runs?.items || []
    const activeRuns = runList.filter((r) => r.status === 'queued' || r.status === 'running')
    const isScriptRunning = activeRuns.some((r) => r.stage === 'script')
    const isRenderRunning = activeRuns.some((r) => r.stage === 'render')
    const isLayoutRunning = activeRuns.some((r) => r.stage === 'layout' || r.stage === 'writeback')
    const isContinueRunning = activeRuns.some((r) => r.stage === 'continue')

    const generatedImages: GeneratedImage[] = generatedImagesData?.items || []
    const composedPages: ComposedPage[] = layoutResult?.pages || []

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
                                    <Select.Option value="openai">OpenAI (GPT-Image)</Select.Option>
                                    <Select.Option value="gemini">Gemini (Nano Banana)</Select.Option>
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
                                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                                    {generatedImages.map((img) => (
                                        <div key={img.id} className="border border-slate-200 rounded-xl p-2.5 bg-white space-y-1.5">
                                            <Image
                                                src={storageFileUrl(img.image_path)}
                                                alt={`Panel ${img.panel_id || img.id}`}
                                                className="w-full rounded"
                                            />
                                            <div className="text-xs font-semibold text-center text-slate-700">
                                                Panel {img.panel_id}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                <div className="flex justify-between pt-2">
                                    <Button onClick={() => setActiveStep(1)}>← 返回调整分镜或对白</Button>
                                    <Button theme="solid" size="large" onClick={() => layoutMutation.mutate()}>
                                        合成漫画排版与对白气泡 →
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* STEP 3: FINAL COMPOSED PAGES & WRITEBACK */}
                {activeStep === 3 && (
                    <div className="space-y-5 pt-2">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="text-sm text-slate-600">
                                将所有分镜原画按页面模板裁切镶框，绘制无遮挡中文/日文漫画气泡，并自动执行记忆回写。
                            </div>
                            <div className="flex gap-2">
                                <Button
                                    loading={layoutMutation.isPending || isLayoutRunning}
                                    onClick={() => layoutMutation.mutate()}
                                >
                                    {composedPages.length > 0 ? '重新合成排版' : '开始合成漫画页'}
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
                            <div className="manga-paper-bg rounded-2xl p-4 md:p-8 flex flex-col items-center gap-6">
                                {composedPages.map((page) => (
                                    <div
                                        key={page.page_number}
                                        className="w-full max-w-2xl bg-white rounded-lg shadow-lg border border-slate-200 overflow-hidden"
                                    >
                                        <div className="px-4 py-2 bg-slate-50 border-b border-slate-100 flex justify-between text-xs text-slate-500">
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
                    </div>
                )}
            </div>

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
