import { formatEpisodeLabel } from '@/utils/episode'
import { useState, useRef, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import {
    Spin,
    Button,
    Table,
    Tag,
    Modal,
    Form,
    Select,
    Toast,
    Empty,
    Input,
    TextArea,
    Descriptions,
    Checkbox,
    RadioGroup,
    Banner,
} from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import {
    IconPlus,
    IconForward,
    IconDelete,
    IconCopy,
    IconRefresh,
    IconSearch,
    IconLink,
    IconBolt,
    IconEdit,
    IconImage,
} from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    projectService,
    branchService,
    episodeService,
    memoryService,
    generationService,
    pitService,
    assetService,
    assetImageService,
    storageFileUrl,
} from '@/services/project'
import type {
    Episode,
    Pit,
    Branch,
    DiffResponse,
    MergeItem,
    Asset,
    AssetClusterResponse,
    AssetClusterItem,
} from '@/services/project'
import StoryAtlas from '@/components/StoryAtlas'
import UsagePanel from '@/components/UsagePanel'

const STATUS_META: Record<string, { label: string; color: TagColor }> = {
    imported: { label: '已导入 · 待理解', color: 'blue' },
    understood: { label: '已理解剧情', color: 'cyan' },
    scripted: { label: '已生成分镜', color: 'green' },
    rendered: { label: '已生成原画', color: 'orange' },
    published: { label: '已排版成稿', color: 'purple' },
    draft: { label: '续画草稿', color: 'grey' },
    generating: { label: '生成中', color: 'violet' },
}

const PIT_STATUS_META: Record<string, { label: string; color: TagColor }> = {
    open: { label: '待回收伏笔', color: 'blue' },
    resolved: { label: '已回收', color: 'green' },
    abandoned: { label: '已搁置', color: 'grey' },
}

const CATEGORY_LABELS: Record<string, { text: string; color: TagColor }> = {
    regular: { text: '正篇', color: 'blue' },
    special: { text: '番外', color: 'orange' },
    extra: { text: '加笔', color: 'purple' },
}

const ASSET_TYPE_OPTIONS = [
    { value: 'character', label: '核心角色' },
    { value: 'item', label: '关键物品/道具' },
    { value: 'location', label: '重要场景/地点' },
    { value: 'outfit', label: '服装造型' },
    { value: 'style', label: '画风基准' },
]

const ASSET_TYPE_META: Record<string, { label: string; color: TagColor }> = {
    character: { label: '角色', color: 'blue' },
    item: { label: '道具物品', color: 'orange' },
    location: { label: '关键场景', color: 'green' },
    outfit: { label: '服装造型', color: 'purple' },
    style: { label: '画风基准', color: 'cyan' },
}

interface ImportFormValues {
    branch_id: string
    number: number
    label?: string
    title?: string
    category?: string
    auto_understand?: boolean
}

function splitPitClues(desc?: string): { summary: string; clues: string[] } {
    if (!desc) return { summary: '', clues: [] }
    const summaryLines: string[] = []
    const clues: string[] = []
    for (const raw of desc.split('\n')) {
        const line = raw.trim()
        if (!line) continue
        if (line.startsWith('[第') && line.includes('线索]')) {
            clues.push(line)
        } else {
            summaryLines.push(line)
        }
    }
    return { summary: summaryLines.join(' '), clues }
}

export default function ProjectDetail() {
    const { id: projectId } = useParams<{ id: string }>()
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const queryClient = useQueryClient()

    const rawView = searchParams.get('view') || 'episodes'
    const activeView = rawView === 'atlas' ? 'characters' : rawView
    const [pitViewMode, setPitViewMode] = useState<'timeline' | 'table'>('timeline')
    const [showImport, setShowImport] = useState(false)
    const [showContinue, setShowContinue] = useState(false)
    const [showCreatePit, setShowCreatePit] = useState(false)
    const [showResolvePit, setShowResolvePit] = useState(false)
    const [resolvingPit, setResolvingPit] = useState<Pit | null>(null)
    const [selectedBranch, setSelectedBranch] = useState<string | undefined>()
    const [uploadFiles, setUploadFiles] = useState<File[]>([])

    const [canonDraft, setCanonDraft] = useState<string | null>(null)
    const [canonValid, setCanonValid] = useState(true)
    const [longSummaryDraft, setLongSummaryDraft] = useState('')
    const [editingSummary, setEditingSummary] = useState(false)

    const [ragQuery, setRagQuery] = useState('')
    const [ragResults, setRagResults] = useState<Array<{ score: number; payload: Record<string, unknown> }>>([])
    const [pitStatusFilter, setPitStatusFilter] = useState<string | undefined>('open')
    const [batchTaskNotice, setBatchTaskNotice] = useState<string | null>(null)

    const [continueForm, setContinueForm] = useState({
        base_episode_id: '',
        tone: 'main',
        context_profile: 'quality' as 'quality' | 'balanced' | 'cost',
        custom_instructions: '',
        title: '',
        image_backend: undefined as string | undefined,
        image_model: undefined as string | undefined,
        image_size: '1024x1024',
    })

    const [showCreateBranch, setShowCreateBranch] = useState(false)
    const [showFork, setShowFork] = useState(false)
    const [showDiff, setShowDiff] = useState(false)
    const [showMerge, setShowMerge] = useState(false)
    const [diffResult, setDiffResult] = useState<DiffResponse | null>(null)
    const [mergeItems, setMergeItems] = useState<MergeItem[]>([])
    const [mergeSourceBranch, setMergeSourceBranch] = useState('')
    const [mergeTargetBranch, setMergeTargetBranch] = useState('')

    const [assetTypeFilter, setAssetTypeFilter] = useState<string | undefined>()
    const [assetViewMode, setAssetViewMode] = useState<'gallery' | 'table'>('gallery')
    const [showCreateAsset, setShowCreateAsset] = useState(false)
    const [editingAsset, setEditingAsset] = useState<Asset | null>(null)
    const [showClusterResult, setShowClusterResult] = useState(false)
    const [clusterData, setClusterData] = useState<AssetClusterResponse | null>(null)
    const [showSimilar, setShowSimilar] = useState(false)
    const [similarAssets, setSimilarAssets] = useState<AssetClusterItem[]>([])
    const [imageAsset, setImageAsset] = useState<Asset | null>(null)
    const [uploadImageKind, setUploadImageKind] = useState<string>('reference')
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
    const [showAssetMerge, setShowAssetMerge] = useState(false)

    const [episodePage, setEpisodePage] = useState(1)
    const [episodePageSize, setEpisodePageSize] = useState(50)
    const [assetPage, setAssetPage] = useState(1)
    const assetPageSize = 48
    const [pitPage, setPitPage] = useState(1)
    const [pitPageSize, setPitPageSize] = useState(50)

    const { data: project, isLoading: projectLoading } = useQuery({
        queryKey: ['project', projectId],
        queryFn: () => projectService.get(projectId!),
        enabled: !!projectId,
        refetchInterval: batchTaskNotice ? 4000 : false,
    })

    const { data: branches } = useQuery({
        queryKey: ['branches', projectId],
        queryFn: () => branchService.list(projectId!),
        enabled: !!projectId,
    })

    const { data: episodesData, isLoading: episodesLoading } = useQuery({
        queryKey: ['episodes', projectId, selectedBranch, episodePage, episodePageSize],
        queryFn: () => episodeService.list(projectId!, selectedBranch, { page: episodePage, page_size: episodePageSize }),
        enabled: !!projectId,
        refetchInterval: batchTaskNotice ? 3500 : false,
    })

    const { data: pitsData, isLoading: pitsLoading } = useQuery({
        queryKey: ['pits', projectId, pitStatusFilter, pitPage, pitPageSize],
        queryFn: () => pitService.list(projectId!, pitStatusFilter || undefined, { page: pitPage, page_size: pitPageSize }),
        enabled: !!projectId,
        refetchInterval: batchTaskNotice ? 4500 : false,
    })

    const { data: assetsData, isLoading: assetsLoading } = useQuery({
        queryKey: ['assets', projectId, assetTypeFilter, assetPage, assetPageSize],
        queryFn: () => assetService.list(projectId!, assetTypeFilter || undefined, { page: assetPage, page_size: assetPageSize }),
        enabled: !!projectId,
        refetchInterval: batchTaskNotice ? 4500 : false,
    })

    const { data: assetImagesData, isLoading: assetImagesLoading } = useQuery({
        queryKey: ['asset-images', imageAsset?.id],
        queryFn: () => assetImageService.list(imageAsset!.id),
        enabled: !!imageAsset,
    })

    const defaultCanonText = useMemo(() => {
        if (!project) return '{}'
        const rawCanon = { ...(project.canon_rules || {}) }
        delete rawCanon.story_bible
        return JSON.stringify(rawCanon, null, 2)
    }, [project])
    const canonText = canonDraft ?? defaultCanonText

    const mainBranch = useMemo(
        () => branches?.find((b) => b.is_default) || branches?.[0],
        [branches],
    )

    const episodes = useMemo(() => episodesData?.items || [], [episodesData])
    const unanalyzedCount = useMemo(
        () => episodes.filter((e) => e.status === 'imported').length,
        [episodes],
    )
    const understoodCount = useMemo(
        () => episodes.filter((e) => ['understood', 'scripted', 'rendered', 'published'].includes(e.status)).length,
        [episodes],
    )

    const activeBatchNotice = batchTaskNotice && unanalyzedCount > 0 ? batchTaskNotice : null

    // Default base episode for Continue modal = latest episode on branch
    const openContinueModal = (presetEpisodeId?: string) => {
        const defaultEp =
            (presetEpisodeId && episodes.find((e) => e.id === presetEpisodeId)) ||
            [...episodes].reverse().find((e) => ['understood', 'published'].includes(e.status)) ||
            episodes[episodes.length - 1]
        setContinueForm((prev) => ({
            ...prev,
            base_episode_id: defaultEp?.id || '',
        }))
        setShowContinue(true)
    }

    const epLabelById = useMemo(() => {
        const m: Record<string, string> = {}
        for (const ep of episodes) {
            m[ep.id] = `第 ${ep.label || ep.number} 话`
        }
        return m
    }, [episodes])

    const uploadImageMutation = useMutation({
        mutationFn: (file: File) => assetImageService.upload(imageAsset!.id, file, uploadImageKind),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['asset-images', imageAsset?.id] })
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            Toast.success('参考图已上传')
        },
        onError: () => {},
    })

    const deleteImageMutation = useMutation({
        mutationFn: (imageId: string) => assetImageService.remove(imageId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['asset-images', imageAsset?.id] })
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            queryClient.invalidateQueries({ queryKey: ['story-graph', projectId] })
        },
        onError: () => {},
    })

    const setPrimaryImageMutation = useMutation({
        mutationFn: (imageId: string) => assetImageService.setPrimary(imageId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['asset-images', imageAsset?.id] })
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            queryClient.invalidateQueries({ queryKey: ['story-graph', projectId] })
            Toast.success('已设为主头像（图谱与后续识图将优先使用）')
        },
        onError: () => {},
    })

    const importMutation = useMutation({
        mutationFn: async (data: {
            branch_id: string
            number: number
            label?: string
            title?: string
            category?: string
            auto_understand?: boolean
            files: File[]
        }) => {
            const formData = new FormData()
            formData.append('branch_id', data.branch_id)
            formData.append('number', String(data.number))
            if (data.label) formData.append('label', data.label)
            if (data.title) formData.append('title', data.title)
            if (data.category) formData.append('category', data.category)
            if (data.auto_understand) formData.append('auto_understand', 'true')
            data.files.forEach((f) => formData.append('files', f))
            return episodeService.importFiles(projectId!, formData)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowImport(false)
            setUploadFiles([])
            Toast.success('章节已导入')
        },
        onError: () => {},
    })

    const batchUnderstandMutation = useMutation({
        mutationFn: (force: boolean) =>
            generationService.triggerBatchUnderstand({
                project_id: projectId!,
                branch_id: selectedBranch || mainBranch?.id,
                force,
            }),
        onSuccess: (res) => {
            if (res.total === 0) {
                Toast.info('当前分支没有待理解的新章节')
                return
            }
            setBatchTaskNotice(`正在按话数顺序理解全书（共 ${res.total} 话），人物设定、主线脉络与伏笔将自动跨话传递...`)
            Toast.success(`已提交 ${res.total} 话按序理解任务`)
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
        },
        onError: () => {},
    })

    const singleUnderstandMutation = useMutation({
        mutationFn: (episodeId: string) => generationService.triggerUnderstand(episodeId),
        onSuccess: () => {
            Toast.success('已启动本话多模态理解')
            setBatchTaskNotice('正在执行章节多模态剧情与人物识别...')
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
        },
        onError: () => {},
    })

    const continueMutation = useMutation({
        mutationFn: () => {
            const baseEpisode = episodes.find((e: Episode) => e.id === continueForm.base_episode_id)
            if (!baseEpisode) return Promise.reject(new Error('请选择作为续画起点的基础章节'))
            return generationService.triggerContinue({
                project_id: projectId!,
                branch_id: baseEpisode.branch_id,
                base_episode_number: baseEpisode.number,
                tone: continueForm.tone,
                context_profile: continueForm.context_profile,
                custom_instructions: continueForm.custom_instructions || undefined,
                title: continueForm.title || undefined,
                image_backend: continueForm.image_backend,
                image_model: continueForm.image_model,
                image_size: continueForm.image_size || '1024x1024',
            })
        },
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowContinue(false)
            Toast.success('全流程续画流水线已启动')
            navigate(`/projects/${projectId}/episodes/${data.episode_id}/generate`)
        },
        onError: () => {},
    })

    const createPitMutation = useMutation({
        mutationFn: (data: {
            title: string
            description?: string
            priority?: number
            introduced_episode_id: string
            trigger_hint?: string
        }) => pitService.create(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            setShowCreatePit(false)
            Toast.success('伏笔已记录')
        },
        onError: () => {},
    })

    const resolvePitMutation = useMutation({
        mutationFn: (data: { pitId: string; resolvedEpisodeId: string }) =>
            pitService.resolve(data.pitId, data.resolvedEpisodeId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            setShowResolvePit(false)
            setResolvingPit(null)
            Toast.success('伏笔已标记为回收')
        },
        onError: () => {},
    })

    const deleteEpisodeMutation = useMutation({
        mutationFn: (episodeId: string) => episodeService.delete(episodeId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            Toast.success('章节已删除')
        },
        onError: () => {},
    })

    const createBranchMutation = useMutation({
        mutationFn: (data: { name: string; description?: string }) => branchService.create(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            setShowCreateBranch(false)
            Toast.success('分支已创建')
        },
        onError: () => {},
    })

    const deleteBranchMutation = useMutation({
        mutationFn: (branchId: string) => branchService.delete(branchId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            Toast.success('分支已删除')
        },
        onError: () => {},
    })

    const forkMutation = useMutation({
        mutationFn: (data: { episode_id: string; branch_name: string; description?: string }) =>
            branchService.fork(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowFork(false)
            Toast.success('已从指定章节派生平行世界线分支')
        },
        onError: () => {},
    })

    const diffMutation = useMutation({
        mutationFn: (data: { source_branch_id: string; target_branch_id: string; episode_number?: number }) =>
            branchService.diff(projectId!, data),
        onSuccess: (data) => {
            setDiffResult(data)
        },
        onError: () => {},
    })

    const mergeMutation = useMutation({
        mutationFn: (data: { source_branch_id: string; target_branch_id: string; items: MergeItem[] }) =>
            branchService.merge(projectId!, data),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            setShowMerge(false)
            setDiffResult(null)
            setMergeItems([])
            if (data.errors.length > 0) {
                Toast.warning(`已合并 ${data.merged_items.length} 项，警告：${data.errors.join(', ')}`)
            } else {
                Toast.success(`成功合并 ${data.merged_items.length} 项变更`)
            }
        },
        onError: () => {},
    })

    const createAssetMutation = useMutation({
        mutationFn: (data: { type: string; name: string; description?: string; visual_tags?: string }) => {
            const vtags = (data.visual_tags || '')
                .split(/[,，]/)
                .map((s) => s.trim())
                .filter(Boolean)
            return assetService.create(projectId!, {
                type: data.type,
                name: data.name,
                description: data.description,
                tags: vtags.length ? { visual_tags: vtags } : undefined,
            })
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setShowCreateAsset(false)
            Toast.success('视觉资产已创建')
        },
        onError: () => {},
    })

    const updateAssetMutation = useMutation({
        mutationFn: (data: { assetId: string; updates: { name?: string; description?: string; tags?: Record<string, unknown> } }) =>
            assetService.update(data.assetId, data.updates),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setEditingAsset(null)
            Toast.success('资产信息已保存')
        },
        onError: () => {},
    })

    const deleteAssetMutation = useMutation({
        mutationFn: (assetId: string) => assetService.delete(assetId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            Toast.success('资产已删除')
        },
        onError: () => {},
    })

    const clusterMutation = useMutation({
        mutationFn: () => assetService.cluster(projectId!, assetTypeFilter),
        onSuccess: (data) => {
            setClusterData(data)
            setShowClusterResult(true)
        },
        onError: () => {},
    })

    const assetMergeMutation = useMutation({
        mutationFn: (data: { source_asset_ids: string[]; target_name: string; target_description?: string }) =>
            assetService.merge(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setShowAssetMerge(false)
            setSelectedAssetIds([])
            Toast.success('同名/相似资产已合并')
        },
        onError: () => {},
    })

    const updateLanguageMutation = useMutation({
        mutationFn: (language: string) => projectService.update(projectId!, { language }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['project', projectId] })
            Toast.success('记忆与输出偏好语言已更新')
        },
        onError: () => {},
    })

    const consolidateMemoryMutation = useMutation({
        mutationFn: () => memoryService.consolidate(projectId!),
        onSuccess: (res) => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            queryClient.invalidateQueries({ queryKey: ['story-graph', projectId] })
            Toast.success(res.summary || '记忆库整理完成')
        },
        onError: () => {},
    })

    if (projectLoading) {
        return (
            <div className="py-20 flex justify-center">
                <Spin size="large" />
            </div>
        )
    }
    if (!project) return <Empty description="未找到该连载项目" />

    const storyBible = project.canon_rules?.story_bible
    const mainPlot = storyBible?.main_plot
    const coreRules = storyBible?.core_rules || []
    const discoveredRules = storyBible?.discovered_rules || []
    const arcSummaries = storyBible?.arc_summaries || []

    const handleDiffForMerge = (sourceId: string, targetId: string) => {
        setMergeSourceBranch(sourceId)
        setMergeTargetBranch(targetId)
        diffMutation.mutate(
            { source_branch_id: sourceId, target_branch_id: targetId },
            {
                onSuccess: (data) => {
                    const items: MergeItem[] = []
                    data.episodes.forEach((ep) => {
                        if (ep.source_episode_id && ep.source_status && !ep.target_status) {
                            items.push({ item_type: 'episode', source_id: ep.source_episode_id, action: 'adopt' })
                        }
                    })
                    data.assets.forEach((asset) => {
                        if (asset.asset_id && asset.in_source && !asset.in_target) {
                            items.push({ item_type: 'asset', source_id: asset.asset_id, action: 'adopt' })
                        }
                    })
                    data.pits.forEach((pit) => {
                        if (pit.source_pit_id && pit.status_source && !pit.status_target) {
                            items.push({ item_type: 'pit', source_id: pit.source_pit_id, action: 'adopt' })
                        }
                    })
                    setMergeItems(items)
                },
            },
        )
    }

    const episodeColumns = [
        {
            title: '话数',
            dataIndex: 'label',
            key: 'label',
            width: 112,
            render: (text: string, record: Episode) => (
                <span className="font-mono font-semibold text-[var(--text-primary)]">
                    {formatEpisodeLabel(text, record.number)}
                </span>
            ),
        },
        {
            title: '章节标题',
            dataIndex: 'title',
            key: 'title',
            render: (text: string, record: Episode) => (
                <span
                    className="font-medium text-[var(--text-primary)] hover:text-[var(--accent)] cursor-pointer transition-colors"
                    onClick={() => navigate(`/projects/${projectId}/episodes/${record.id}`)}
                >
                    {text || '（未命名章节）'}
                </span>
            ),
        },
        {
            title: '类型',
            dataIndex: 'category',
            key: 'category',
            width: 84,
            render: (text: string) => {
                const cat = CATEGORY_LABELS[text]
                return cat ? <Tag color={cat.color}>{cat.text}</Tag> : <Tag>{text}</Tag>
            },
        },
        {
            title: '来源',
            dataIndex: 'source',
            key: 'source',
            width: 110,
            render: (text: string) => (
                <Tag color={text === 'generated' ? 'violet' : 'grey'}>
                    {text === 'generated' ? '续画成稿' : text === 'import_mangadex' ? 'MangaDex' : '原作导入'}
                </Tag>
            ),
        },
        {
            title: '当前状态',
            dataIndex: 'status',
            key: 'status',
            width: 140,
            render: (text: string) => {
                const m = STATUS_META[text]
                return <Tag color={m?.color || ('default' as TagColor)}>{m?.label || text}</Tag>
            },
        },
        {
            title: '更新时间',
            dataIndex: 'updated_at',
            key: 'updated_at',
            width: 120,
            render: (text: string) => (
                <span className="text-[13px] font-mono text-[var(--text-muted)]">{new Date(text).toLocaleDateString()}</span>
            ),
        },
        {
            title: '操作',
            key: 'actions',
            width: 350,
            render: (_: unknown, record: Episode) => (
                <div className="flex flex-nowrap items-center gap-1.5 whitespace-nowrap">
                    <Button size="small" onClick={() => navigate(`/projects/${projectId}/episodes/${record.id}`)}>
                        阅读与解析
                    </Button>
                    {record.status === 'imported' && (
                        <Button
                            size="small"
                            theme="light"
                            type="primary"
                            icon={<IconBolt />}
                            loading={singleUnderstandMutation.isPending}
                            onClick={() => singleUnderstandMutation.mutate(record.id)}
                        >
                            理解本话
                        </Button>
                    )}
                    {record.source === 'generated' && (
                        <Button
                            size="small"
                            theme="light"
                            onClick={() => navigate(`/projects/${projectId}/episodes/${record.id}/generate`)}
                        >
                            分镜工坊
                        </Button>
                    )}
                    {['understood', 'published'].includes(record.status) && (
                        <Button
                            size="small"
                            icon={<IconForward />}
                            onClick={() => openContinueModal(record.id)}
                        >
                            续画
                        </Button>
                    )}
                    <Button
                        size="small"
                        type="danger"
                        theme="borderless"
                        icon={<IconDelete />}
                        onClick={() => {
                            Modal.confirm({
                                title: '确认删除该章节？',
                                content: `将删除“第 ${record.label} 话 ${record.title || ''}”，关联伏笔状态将自动安全回退。`,
                                onOk: () => deleteEpisodeMutation.mutate(record.id),
                            })
                        }}
                    />
                </div>
            ),
        },
    ]

    const pitColumns = [
        {
            title: '优先级',
            dataIndex: 'priority',
            key: 'priority',
            width: 110,
            render: (prio: number) =>
                prio >= 8 ? (
                    <Tag color="red">主线核心 ({prio})</Tag>
                ) : prio >= 4 ? (
                    <Tag color="orange">重要支线 ({prio})</Tag>
                ) : (
                    <Tag color="grey">细节线索 ({prio})</Tag>
                ),
        },
        {
            title: '伏笔与悬念详情',
            dataIndex: 'title',
            key: 'title',
            render: (_: string, record: Pit) => {
                const { summary, clues } = splitPitClues(record.description || record.title)
                return (
                    <div className="space-y-1.5 py-1">
                        <div className="font-semibold text-[var(--text-primary)] text-sm">{record.title}</div>
                        {summary && summary !== record.title && (
                            <div className="text-xs text-[var(--text-secondary)] leading-relaxed">{summary}</div>
                        )}
                        {clues.length > 0 && (
                            <div className="space-y-1 pt-1">
                                {clues.map((c, idx) => (
                                    <div
                                        key={idx}
                                        className="text-xs bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-secondary)] rounded-[4px] px-2 py-1"
                                    >
                                        {c}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )
            },
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            width: 110,
            render: (text: string) => {
                const m = PIT_STATUS_META[text]
                return <Tag color={m?.color || ('default' as TagColor)}>{m?.label || text}</Tag>
            },
        },
        {
            title: '埋设 / 回收章节',
            dataIndex: 'introduced_episode_id',
            key: 'introduced_episode_id',
            width: 160,
            render: (introId: string, record: Pit) => (
                <div className="space-y-1 text-xs">
                    <div>
                        <span className="text-[var(--text-muted)]">埋设：</span>
                        <span
                            className="text-[var(--accent)] hover:underline cursor-pointer"
                            onClick={() => navigate(`/projects/${projectId}/episodes/${introId}`)}
                        >
                            {epLabelById[introId] || '查看章节'}
                        </span>
                    </div>
                    {record.resolved_episode_id && (
                        <div>
                            <span className="text-[var(--text-muted)]">回收：</span>
                            <span
                                className="text-emerald-500 hover:underline cursor-pointer"
                                onClick={() => navigate(`/projects/${projectId}/episodes/${record.resolved_episode_id}`)}
                            >
                                {epLabelById[record.resolved_episode_id] || '查看章节'}
                            </span>
                        </div>
                    )}
                </div>
            ),
        },
        {
            title: '回收触发条件',
            dataIndex: 'trigger_hint',
            key: 'trigger_hint',
            width: 220,
            render: (text: string) => <span className="text-xs text-[var(--text-muted)]">{text || '-'}</span>,
        },
        {
            title: '操作',
            key: 'actions',
            width: 110,
            render: (_: unknown, record: Pit) =>
                record.status === 'open' ? (
                    <Button
                        size="small"
                        theme="light"
                        type="primary"
                        onClick={() => {
                            setResolvingPit(record)
                            setShowResolvePit(true)
                        }}
                    >
                        标记回收
                    </Button>
                ) : null,
        },
    ]

    const branchColumns = [
        {
            title: '分支名称',
            dataIndex: 'name',
            key: 'name',
            render: (text: string, record: Branch) => (
                <span className="flex items-center gap-2 font-medium">
                    {text}
                    {record.is_default && (
                        <Tag color="green" size="small">
                            主世界线
                        </Tag>
                    )}
                </span>
            ),
        },
        { title: '分支说明', dataIndex: 'description', key: 'description', render: (t: string) => t || '-' },
        { title: '章节数', dataIndex: 'episode_count', key: 'episode_count', width: 90, render: (t: number) => t ?? 0 },
        {
            title: '最新话数',
            dataIndex: 'latest_episode_number',
            key: 'latest_episode_number',
            width: 110,
            render: (t: number | null) => (t != null ? `第 ${t} 话` : '-'),
        },
        {
            title: '派生自',
            dataIndex: 'base_branch_id',
            key: 'base_branch_id',
            width: 130,
            render: (t: string) => {
                if (!t) return '-'
                const b = branches?.find((item) => item.id === t)
                return b ? <Tag>{b.name}</Tag> : t
            },
        },
        {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, record: Branch) =>
                !record.is_default ? (
                    <Button
                        size="small"
                        type="danger"
                        theme="light"
                        icon={<IconDelete />}
                        loading={deleteBranchMutation.isPending}
                        onClick={() => {
                            Modal.confirm({
                                title: '删除平行分支',
                                content: `确认删除分支 "${record.name}" 及其下属章节？`,
                                onOk: () => deleteBranchMutation.mutate(record.id),
                            })
                        }}
                    />
                ) : null,
        },
    ]

    const assets = assetsData?.items || []
    const isFullBleedAtlas =
        activeView === 'characters' ||
        activeView === 'qa' ||
        (activeView === 'pits' && pitViewMode === 'timeline')

    return (
        <div className={isFullBleedAtlas ? 'h-full w-full flex flex-col overflow-hidden' : 'space-y-6'}>
            {isFullBleedAtlas ? (
                <div className="flex-1 min-h-0 flex flex-col">
                    {activeView === 'pits' && (
                        <div className="h-9 shrink-0 px-4 border-b border-[var(--border)] bg-[var(--bg-panel)] flex items-center justify-between text-xs">
                            <span className="text-[var(--text-muted)]">
                                伏笔追踪时间线 · {pitsData?.total || 0} 条{pitStatusFilter === 'open' ? '待回收' : ''}
                            </span>
                            <div className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => setPitViewMode('table')}
                                    className="px-2 py-0.5 rounded-[4px] border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] cursor-pointer transition-colors"
                                >
                                    管理列表
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setShowCreatePit(true)}
                                    className="px-2 py-0.5 rounded-[4px] bg-[var(--accent)] text-white font-medium hover:opacity-90 cursor-pointer transition-opacity"
                                >
                                    + 手动埋设伏笔
                                </button>
                            </div>
                        </div>
                    )}
                    <div className="flex-1 min-h-0 flex flex-col">
                        {projectId && (
                            <StoryAtlas
                                projectId={projectId}
                                defaultBranchId={selectedBranch}
                                mode={activeView as 'characters' | 'pits' | 'qa'}
                            />
                        )}
                    </div>
                </div>
            ) : (
                <>
                    {/* Compact Editorial Masthead & Inline Summary Strip */}
                    <header className="pb-5 border-b border-[var(--border)] space-y-3">
                        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
                            <div className="space-y-2 min-w-0">
                                <div className="flex flex-wrap items-center gap-2.5">
                                    <h1 className="font-editorial text-2xl font-bold tracking-tight text-[var(--text-primary)] m-0">
                                        {project.title}
                                    </h1>
                                    <Select
                                        size="small"
                                        value={project.language || 'zh'}
                                        loading={updateLanguageMutation.isPending}
                                        onChange={(val) => updateLanguageMutation.mutate(String(val))}
                                        style={{ width: 112 }}
                                        optionList={[
                                            { value: 'zh', label: '简体中文' },
                                            { value: 'en', label: 'English' },
                                            { value: 'ja', label: '日本語' },
                                        ]}
                                    />
                                    {storyBible?.art_style && (
                                        <span className="px-2 py-0.5 rounded-[4px] border border-[var(--border)] bg-[var(--bg-panel)] text-xs font-medium text-[var(--text-secondary)]">
                                            画风已锚定
                                        </span>
                                    )}
                                </div>
                                <p className="text-sm text-[var(--text-secondary)] m-0 max-w-3xl leading-relaxed">
                                    {project.description || '导入连载章节并执行多模态理解后，系统将自动提取人物/道具/场景设定、主线脉络与伏笔。'}
                                </p>
                            </div>

                            <div className="flex flex-wrap items-center gap-2 shrink-0">
                                <Button
                                    icon={<IconLink />}
                                    onClick={() => navigate(`/projects/${projectId}/imports/mangadex`)}
                                >
                                    MangaDex 抓取
                                </Button>
                                <Button
                                    icon={<IconPlus />}
                                    onClick={() => setShowImport(true)}
                                >
                                    导入章节
                                </Button>
                                <Button
                                    icon={<IconBolt />}
                                    loading={batchUnderstandMutation.isPending}
                                    onClick={() => batchUnderstandMutation.mutate(false)}
                                >
                                    一键理解全书{unanalyzedCount > 0 ? ` (${unanalyzedCount})` : ''}
                                </Button>
                                <Button
                                    icon={<IconForward />}
                                    theme="solid"
                                    disabled={episodes.length === 0}
                                    onClick={() => openContinueModal()}
                                >
                                    智能续画下一话
                                </Button>
                            </div>
                        </div>

                        {/* Inline Monospace Summary Strip (No KPI Card Grid) */}
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-[var(--text-secondary)] font-mono pt-1">
                            <span>
                                连载 <strong className="text-[var(--text-primary)]">{episodesData?.total || 0}</strong> 话（已理解 {understoodCount}）
                            </span>
                            <span className="text-[var(--border)]">/</span>
                            <span>
                                资产 <strong className="text-[var(--text-primary)]">{assetsData?.total || 0}</strong> 项
                            </span>
                            <span className="text-[var(--border)]">/</span>
                            <span>
                                伏笔 <strong className="text-[var(--accent)]">{pitsData?.total || 0}</strong> 条
                            </span>
                            {mainPlot?.current_arc && (
                                <>
                                    <span className="text-[var(--border)]">/</span>
                                    <span className="font-sans text-[var(--text-primary)] truncate max-w-lg">
                                        当前篇章：{mainPlot.current_arc}
                                    </span>
                                </>
                            )}
                        </div>
                    </header>

                    {activeBatchNotice && (
                        <Banner
                            type="info"
                            description={activeBatchNotice}
                            onClose={() => setBatchTaskNotice(null)}
                        />
                    )}

                    {/* VIEW: EPISODES */}
                    {activeView === 'episodes' && (
                        <section className="space-y-4">
                            <div className="flex flex-wrap justify-between items-center gap-3">
                                <div className="flex items-center gap-2">
                                    <span className="text-[13px] text-[var(--text-secondary)] font-medium">世界线分支：</span>
                                    <Select
                                        size="small"
                                        value={selectedBranch || ''}
                                        onChange={(v) => {
                                            setSelectedBranch(v ? String(v) : undefined)
                                            setEpisodePage(1)
                                        }}
                                        style={{ width: 180 }}
                                    >
                                        <Select.Option value="">全部分支</Select.Option>
                                        {branches?.map((b) => (
                                            <Select.Option key={b.id} value={b.id}>
                                                {b.name} {b.is_default ? '(默认)' : ''}
                                            </Select.Option>
                                        ))}
                                    </Select>
                                </div>
                                <div className="flex items-center gap-2">
                                    {understoodCount > 0 && (
                                        <Button
                                            size="small"
                                            loading={consolidateMemoryMutation.isPending}
                                            onClick={() => consolidateMemoryMutation.mutate()}
                                        >
                                            一键整理记忆库
                                        </Button>
                                    )}
                                    {episodes.length > 0 && (
                                        <Button
                                            size="small"
                                            icon={<IconRefresh />}
                                            onClick={() => {
                                                Modal.confirm({
                                                    title: '重新按序理解全部章节？',
                                                    content: '将从第 1 话起按顺序重新分析本分支所有章节，刷新人物档案、主线与伏笔。',
                                                    onOk: () => batchUnderstandMutation.mutate(true),
                                                })
                                            }}
                                        >
                                            全分支重跑理解
                                        </Button>
                                    )}
                                </div>
                            </div>

                            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                                <Table
                                    columns={episodeColumns}
                                    dataSource={episodes}
                                    loading={episodesLoading}
                                    rowKey="id"
                                    pagination={{
                                        currentPage: episodePage,
                                        pageSize: episodePageSize,
                                        total: episodesData?.total || 0,
                                        showTotal: true,
                                        onChange: (cp: number, ps: number) => {
                                            setEpisodePage(cp)
                                            setEpisodePageSize(ps)
                                        },
                                    }}
                                />
                            </div>
                        </section>
                    )}

                    {/* VIEW: STORY BIBLE & MAIN PLOTLINE */}
                    {activeView === 'story' && (
                        <section className="space-y-8 max-w-5xl">
                            {/* Main Plotline */}
                            <div className="space-y-4">
                                <div className="flex items-center justify-between pb-2 border-b border-[var(--border)]">
                                    <div>
                                        <h2 className="font-editorial text-lg font-bold text-[var(--text-primary)] m-0">
                                            主线核心脉络与篇章追踪
                                        </h2>
                                        <p className="text-xs text-[var(--text-muted)] m-0 mt-0.5">
                                            由多模态理解引擎随章节推进自动提炼，续画分镜时作为最高优先级叙事纲领注入
                                        </p>
                                    </div>
                                    {storyBible?.last_updated_episode && (
                                        <span className="px-2 py-0.5 rounded-[4px] border border-[var(--border)] bg-[var(--bg-panel)] text-xs font-mono text-[var(--text-secondary)]">
                                            同步至第 {storyBible.last_updated_episode} 话
                                        </span>
                                    )}
                                </div>

                                {!mainPlot?.core_conflict && !mainPlot?.current_arc ? (
                                    <Empty description="尚未提炼主线脉络。请先导入章节并执行「一键理解全书」。" />
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-[var(--border)] rounded-[6px] overflow-hidden border border-[var(--border)]">
                                        <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                                            <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--accent)]">
                                                Core Conflict · 全书核心矛盾
                                            </div>
                                            <div className="text-sm text-[var(--text-primary)] leading-relaxed">
                                                {mainPlot?.core_conflict || '-'}
                                            </div>
                                        </div>
                                        <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                                            <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                                                Current Arc · 当前所在篇章
                                            </div>
                                            <div className="text-sm text-[var(--text-primary)] leading-relaxed">
                                                {mainPlot?.current_arc || '-'}
                                            </div>
                                        </div>
                                        <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                                            <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                                                Protagonist Goal · 主角当前目标
                                            </div>
                                            <div className="text-sm text-[var(--text-primary)] leading-relaxed">
                                                {mainPlot?.protagonist_goal || '-'}
                                            </div>
                                        </div>
                                        <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                                            <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                                                Next Hook · 下一话衔接钩子
                                            </div>
                                            <div className="text-sm text-[var(--text-primary)] leading-relaxed">
                                                {mainPlot?.next_hook || mainPlot?.arc_progress || '-'}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {storyBible?.art_style && (
                                    <div className="rounded-[6px] bg-[var(--bg-panel)] px-4 py-3 border border-[var(--border)] text-xs text-[var(--text-secondary)]">
                                        <span className="font-semibold text-[var(--text-primary)]">原作画风特征锚点：</span>
                                        {storyBible.art_style}
                                    </div>
                                )}
                            </div>

                            {/* Core Foundational Rules */}
                            {coreRules.length > 0 && (
                                <div className="space-y-2.5">
                                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                        奠基核心设定法则 · Core Rules ({coreRules.length})
                                    </h3>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                        {coreRules.map((rule, idx) => (
                                            <div
                                                key={idx}
                                                className="rounded-[4px] bg-[var(--bg-panel)] border-l-2 border-l-[var(--accent)] border border-[var(--border)] px-3.5 py-2.5 text-xs text-[var(--text-primary)] leading-relaxed"
                                            >
                                                {rule}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Auto-discovered World Rules */}
                            {discoveredRules.length > 0 && (
                                <div className="space-y-2.5">
                                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                        自动提炼的世界观与设定法则 ({discoveredRules.length})
                                    </h3>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                        {discoveredRules.map((rule, idx) => (
                                            <div
                                                key={idx}
                                                className="rounded-[4px] bg-[var(--bg-panel)] border border-[var(--border)] px-3.5 py-2 text-xs text-[var(--text-secondary)] leading-relaxed"
                                            >
                                                • {rule}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Arc Summaries */}
                            {arcSummaries.length > 0 && (
                                <div className="space-y-2.5">
                                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                                        层级篇章压缩摘要 ({arcSummaries.length})
                                    </h3>
                                    <div className="divide-y divide-[var(--border)] rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)]">
                                        {arcSummaries.map((arc, idx) => (
                                            <div key={arc.key || idx} className="px-4 py-3 text-xs space-y-1">
                                                <div className="font-mono font-semibold text-[var(--text-primary)]">
                                                    第 {arc.start_episode} – {arc.end_episode} 话
                                                </div>
                                                <div className="text-[var(--text-secondary)] leading-relaxed">{arc.summary}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Rolling Long Summary (Editable) */}
                            <div className="space-y-2.5">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h3 className="text-sm font-semibold text-[var(--text-primary)] m-0">
                                            长程滚动剧情记忆 (Long Summary)
                                        </h3>
                                        <span className="text-xs text-[var(--text-muted)]">
                                            按话数去重累积，超出预算时自动保真压缩关键状态与伏笔
                                        </span>
                                    </div>
                                    {!editingSummary ? (
                                        <Button
                                            size="small"
                                            icon={<IconEdit />}
                                            onClick={() => {
                                                setLongSummaryDraft(project.long_summary || '')
                                                setEditingSummary(true)
                                            }}
                                        >
                                            修订摘要
                                        </Button>
                                    ) : (
                                        <div className="flex gap-2">
                                            <Button
                                                size="small"
                                                onClick={() => {
                                                    setEditingSummary(false)
                                                    setLongSummaryDraft(project.long_summary || '')
                                                }}
                                            >
                                                取消
                                            </Button>
                                            <Button
                                                size="small"
                                                theme="solid"
                                                onClick={() => {
                                                    memoryService
                                                        .updateLongSummary(projectId!, longSummaryDraft)
                                                        .then(() => {
                                                            setEditingSummary(false)
                                                            queryClient.invalidateQueries({ queryKey: ['project', projectId] })
                                                            Toast.success('长程摘要已保存')
                                                        })
                                                        .catch(() => {})
                                                }}
                                            >
                                                保存
                                            </Button>
                                        </div>
                                    )}
                                </div>
                                {editingSummary ? (
                                    <TextArea value={longSummaryDraft} onChange={setLongSummaryDraft} rows={8} />
                                ) : (
                                    <div className="rounded-[6px] bg-[var(--bg-panel)] border border-[var(--border)] p-4 text-sm text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
                                        {project.long_summary || '暂无长程摘要，执行章节理解后自动生成。'}
                                    </div>
                                )}
                            </div>

                            {/* Manual Canon Rules + RAG Search */}
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-2 border-t border-[var(--border)]">
                                <div className="space-y-2">
                                    <h4 className="text-sm font-semibold text-[var(--text-primary)] m-0">
                                        作者硬设定 (Canon Rules JSON)
                                    </h4>
                                    <p className="text-xs text-[var(--text-muted)] m-0">
                                        人工录入不可违背的世界法则、战力体系或人物铁律（自动保留 story_bible）
                                    </p>
                                    <TextArea
                                        value={canonText}
                                        onChange={(val: string) => {
                                            setCanonDraft(val)
                                            try {
                                                JSON.parse(val)
                                                setCanonValid(true)
                                            } catch {
                                                setCanonValid(false)
                                            }
                                        }}
                                        rows={7}
                                        placeholder='{"魔法规则": "咏唱需要星之匣共鸣", "禁忌": "不可在白天开启阁楼暗门"}'
                                    />
                                    <div className="flex items-center gap-2">
                                        <Button
                                            theme="solid"
                                            size="small"
                                            disabled={!canonValid}
                                            onClick={() => {
                                                const parsed = JSON.parse(canonText)
                                                memoryService
                                                    .updateCanonRules(projectId!, parsed)
                                                    .then(() => {
                                                        setCanonDraft(null)
                                                        queryClient.invalidateQueries({ queryKey: ['project', projectId] })
                                                        Toast.success('硬设定已更新')
                                                    })
                                                    .catch(() => {})
                                            }}
                                        >
                                            保存硬设定
                                        </Button>
                                        {!canonValid && <Tag color="red">JSON 格式有误</Tag>}
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <h4 className="text-sm font-semibold text-[var(--text-primary)] m-0">
                                        跨章节剧情记忆检索 (RAG / 分词召回)
                                    </h4>
                                    <p className="text-xs text-[var(--text-muted)] m-0">
                                        输入人物、道具或事件关键词，测试跨话历史记忆召回效果
                                    </p>
                                    <div className="flex gap-2">
                                        <Input
                                            value={ragQuery}
                                            onChange={setRagQuery}
                                            placeholder="例如：星之匣 / 炎龙 / 冰精灵..."
                                        />
                                        <Button
                                            theme="solid"
                                            icon={<IconSearch />}
                                            onClick={() => {
                                                if (!ragQuery.trim()) return
                                                memoryService
                                                    .searchRag(projectId!, ragQuery)
                                                    .then((res) => setRagResults(res.results))
                                                    .catch(() => {})
                                            }}
                                        >
                                            检索
                                        </Button>
                                    </div>
                                    <div className="space-y-2 max-h-56 overflow-y-auto pt-1">
                                        {ragResults.map((r, i) => (
                                            <div
                                                key={i}
                                                className="rounded-[4px] border border-[var(--border)] bg-[var(--bg-panel)] p-2.5 text-xs space-y-1"
                                            >
                                                <div className="flex items-center gap-2">
                                                    {r.payload?.episode_number != null && (
                                                        <span className="font-mono text-[11px] text-[var(--accent)] font-semibold">
                                                            第 {String(r.payload.episode_number)} 话
                                                        </span>
                                                    )}
                                                    <span className="text-[11px] text-[var(--text-muted)]">
                                                        {String(r.payload?.type || 'memory')}
                                                    </span>
                                                    <span className="text-[11px] font-mono text-[var(--text-muted)] ml-auto">
                                                        {r.score?.toFixed(3)}
                                                    </span>
                                                </div>
                                                <div className="text-[var(--text-secondary)] leading-relaxed">
                                                    {String(r.payload?.content || '')}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </section>
                    )}

                    {/* VIEW: VISUAL ASSETS GALLERY */}
                    {activeView === 'assets' && (
                        <section className="space-y-4">
                            <div className="flex flex-wrap justify-between items-center gap-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <Select
                                        size="small"
                                        value={assetTypeFilter || ''}
                                        onChange={(v) => {
                                            setAssetTypeFilter(v ? String(v) : undefined)
                                            setAssetPage(1)
                                        }}
                                        style={{ width: 160 }}
                                    >
                                        <Select.Option value="">全部资产类型</Select.Option>
                                        {ASSET_TYPE_OPTIONS.map((opt) => (
                                            <Select.Option key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </Select.Option>
                                        ))}
                                    </Select>
                                    <RadioGroup
                                        type="button"
                                        buttonSize="small"
                                        value={assetViewMode}
                                        onChange={(e) => setAssetViewMode(e.target.value as 'gallery' | 'table')}
                                        options={[
                                            { label: '图鉴', value: 'gallery' },
                                            { label: '列表', value: 'table' },
                                        ]}
                                    />
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {selectedAssetIds.length >= 2 && (
                                        <Button size="small" icon={<IconCopy />} theme="solid" onClick={() => setShowAssetMerge(true)}>
                                            合并选中 ({selectedAssetIds.length})
                                        </Button>
                                    )}
                                    <Button
                                        size="small"
                                        icon={<IconSearch />}
                                        loading={clusterMutation.isPending}
                                        onClick={() => clusterMutation.mutate()}
                                    >
                                        相似聚类去重
                                    </Button>
                                    <Button size="small" icon={<IconPlus />} theme="solid" onClick={() => setShowCreateAsset(true)}>
                                        新增资产
                                    </Button>
                                </div>
                            </div>

                            {assetsLoading ? (
                                <div className="py-12 flex justify-center">
                                    <Spin />
                                </div>
                            ) : assets.length === 0 ? (
                                <Empty description="暂无资产记录。理解漫画章节后将自动识别角色、关键道具与场景，并自动截取参考图。" />
                            ) : assetViewMode === 'gallery' ? (
                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
                                    {assets.map((asset) => {
                                        const meta = ASSET_TYPE_META[asset.type] || { label: asset.type, color: 'grey' as TagColor }
                                        const epCount = Object.keys(asset.episode_ids || {}).length
                                        const vtags = asset.tags?.visual_tags || []
                                        const checked = selectedAssetIds.includes(asset.id)
                                        return (
                                            <div
                                                key={asset.id}
                                                className={`rounded-[6px] border p-3.5 flex flex-col justify-between space-y-3 transition-colors ${
                                                    checked
                                                        ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                                                        : 'border-[var(--border)] bg-[var(--bg-panel)] hover:border-[var(--text-muted)]'
                                                }`}
                                            >
                                                <div className="space-y-3">
                                                    <div className="flex items-start gap-3">
                                                        <div
                                                            onClick={() => setImageAsset(asset)}
                                                            className="w-18 h-22 rounded-[4px] bg-[var(--bg-canvas)] border border-[var(--border)] overflow-hidden shrink-0 flex items-center justify-center cursor-pointer"
                                                        >
                                                            {asset.preview_image_path ? (
                                                                <img
                                                                    src={storageFileUrl(asset.preview_image_path)}
                                                                    alt={asset.name}
                                                                    className="w-full h-full object-cover"
                                                                />
                                                            ) : (
                                                                <div className="text-center text-[10px] text-[var(--text-muted)] px-1">
                                                                    <IconImage />
                                                                    <div>上传</div>
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div className="min-w-0 flex-1 space-y-1">
                                                            <div className="flex items-start justify-between gap-1">
                                                                <div
                                                                    className="font-semibold text-[var(--text-primary)] text-sm truncate"
                                                                    title={asset.name}
                                                                >
                                                                    {asset.name}
                                                                </div>
                                                                <Checkbox
                                                                    checked={checked}
                                                                    onChange={(e) => {
                                                                        if (e.target.checked) {
                                                                            setSelectedAssetIds([...selectedAssetIds, asset.id])
                                                                        } else {
                                                                            setSelectedAssetIds(selectedAssetIds.filter((id) => id !== asset.id))
                                                                        }
                                                                    }}
                                                                />
                                                            </div>
                                                            <div className="flex flex-wrap gap-1 text-[10px]">
                                                                <span className="px-1.5 py-0.5 rounded-[4px] border border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]">
                                                                    {meta.label}
                                                                </span>
                                                                {epCount > 0 && (
                                                                    <span className="px-1.5 py-0.5 rounded-[4px] border border-[var(--border)] text-[var(--text-muted)] font-mono">
                                                                        {epCount} 话
                                                                    </span>
                                                                )}
                                                                {asset.tags?.role && (
                                                                    <span className="px-1.5 py-0.5 rounded-[4px] border border-[var(--border)] text-[var(--text-muted)]">
                                                                        {asset.tags.role}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            {asset.tags?.aliases && asset.tags.aliases.length > 0 && (
                                                                <div className="text-[11px] text-[var(--text-muted)] truncate">
                                                                    别名：{asset.tags.aliases.join(' / ')}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>

                                                    <p className="text-xs text-[var(--text-secondary)] line-clamp-3 m-0 leading-relaxed">
                                                        {asset.description || '暂无外貌或设定描述'}
                                                    </p>

                                                    {asset.tags?.speech_style && (
                                                        <div className="rounded-[4px] bg-[var(--bg-elevated)] border border-[var(--border)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)]">
                                                            <span className="font-semibold text-[var(--text-primary)]">语气：</span>
                                                            {asset.tags.speech_style}
                                                        </div>
                                                    )}

                                                    {vtags.length > 0 && (
                                                        <div className="flex flex-wrap gap-1">
                                                            {vtags.slice(0, 4).map((t, idx) => (
                                                                <span
                                                                    key={idx}
                                                                    className="text-[10px] bg-[var(--bg-elevated)] text-[var(--text-muted)] px-1.5 py-0.5 rounded-[4px] font-mono"
                                                                >
                                                                    {String(t)}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>

                                                <div className="flex items-center justify-between pt-2.5 border-t border-[var(--border)]">
                                                    <div className="flex gap-1">
                                                        <Button size="small" onClick={() => setImageAsset(asset)}>
                                                            参考图 ({asset.image_count || 0})
                                                        </Button>
                                                        <Button size="small" onClick={() => setEditingAsset(asset)}>
                                                            编辑
                                                        </Button>
                                                    </div>
                                                    <div className="flex gap-1">
                                                        <Button
                                                            size="small"
                                                            theme="borderless"
                                                            icon={<IconSearch />}
                                                            onClick={() => {
                                                                assetService
                                                                    .findSimilar(asset.id)
                                                                    .then((res) => {
                                                                        setSimilarAssets(res)
                                                                        setShowSimilar(true)
                                                                    })
                                                                    .catch(() => {})
                                                            }}
                                                        />
                                                        <Button
                                                            size="small"
                                                            type="danger"
                                                            theme="borderless"
                                                            icon={<IconDelete />}
                                                            onClick={() => {
                                                                Modal.confirm({
                                                                    title: `确认删除资产 "${asset.name}"？`,
                                                                    onOk: () => deleteAssetMutation.mutate(asset.id),
                                                                })
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            ) : (
                                <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                                    <Table
                                        rowKey="id"
                                        dataSource={assets}
                                        pagination={false}
                                        columns={[
                                            { title: '名称', dataIndex: 'name', key: 'name', width: 150 },
                                            {
                                                title: '类型',
                                                dataIndex: 'type',
                                                key: 'type',
                                                width: 110,
                                                render: (t: string) => {
                                                    const m = ASSET_TYPE_META[t]
                                                    return <Tag color={m?.color || 'grey'}>{m?.label || t}</Tag>
                                                },
                                            },
                                            { title: '外貌与设定描述', dataIndex: 'description', key: 'description' },
                                            {
                                                title: '参考图',
                                                dataIndex: 'image_count',
                                                key: 'image_count',
                                                width: 90,
                                                render: (c: number) => `${c || 0} 张`,
                                            },
                                            {
                                                title: '操作',
                                                key: 'actions',
                                                width: 180,
                                                render: (_: unknown, record: Asset) => (
                                                    <div className="flex gap-1">
                                                        <Button size="small" onClick={() => setImageAsset(record)}>
                                                            参考图
                                                        </Button>
                                                        <Button size="small" onClick={() => setEditingAsset(record)}>
                                                            编辑
                                                        </Button>
                                                    </div>
                                                ),
                                            },
                                        ]}
                                    />
                                </div>
                            )}
                        </section>
                    )}

                    {/* VIEW: PITS TABLE MODE */}
                    {activeView === 'pits' && pitViewMode === 'table' && (
                        <section className="space-y-4">
                            <div className="flex flex-wrap justify-between items-center gap-3">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs text-[var(--text-secondary)] font-medium">伏笔状态：</span>
                                    <Select
                                        size="small"
                                        value={pitStatusFilter ?? ''}
                                        onChange={(v) => {
                                            setPitStatusFilter(v ? String(v) : undefined)
                                            setPitPage(1)
                                        }}
                                        style={{ width: 150 }}
                                    >
                                        <Select.Option value="">全部伏笔</Select.Option>
                                        <Select.Option value="open">待回收伏笔</Select.Option>
                                        <Select.Option value="resolved">已回收伏笔</Select.Option>
                                        <Select.Option value="abandoned">已搁置</Select.Option>
                                    </Select>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Button size="small" onClick={() => setPitViewMode('timeline')}>
                                        返回时间线轨道视图
                                    </Button>
                                    <Button size="small" icon={<IconPlus />} theme="solid" onClick={() => setShowCreatePit(true)}>
                                        手动埋设新伏笔
                                    </Button>
                                </div>
                            </div>

                            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                                <Table
                                    columns={pitColumns}
                                    dataSource={pitsData?.items || []}
                                    loading={pitsLoading}
                                    rowKey="id"
                                    pagination={{
                                        currentPage: pitPage,
                                        pageSize: pitPageSize,
                                        total: pitsData?.total || 0,
                                        showTotal: true,
                                        onChange: (cp: number, ps: number) => {
                                            setPitPage(cp)
                                            setPitPageSize(ps)
                                        },
                                    }}
                                />
                            </div>
                        </section>
                    )}

                    {/* VIEW: BRANCHES */}
                    {activeView === 'branches' && (
                        <section className="space-y-6">
                            {projectId && (
                                <StoryAtlas projectId={projectId} defaultBranchId={selectedBranch} mode="branches" />
                            )}

                            <div className="flex flex-wrap justify-between items-center gap-3">
                                <span className="text-xs text-[var(--text-muted)]">
                                    从任意章节 Fork 出独立世界线探索 IF 剧情，续画上下文严格隔离不串线
                                </span>
                                <div className="flex flex-wrap gap-2">
                                    <Button size="small" icon={<IconCopy />} onClick={() => setShowFork(true)}>
                                        派生分支 (Fork)
                                    </Button>
                                    <Button
                                        size="small"
                                        icon={<IconSearch />}
                                        onClick={() => {
                                            setDiffResult(null)
                                            setShowDiff(true)
                                        }}
                                    >
                                        对比差异
                                    </Button>
                                    <Button
                                        size="small"
                                        onClick={() => {
                                            setDiffResult(null)
                                            setShowMerge(true)
                                        }}
                                    >
                                        合并成果
                                    </Button>
                                    <Button size="small" icon={<IconPlus />} theme="solid" onClick={() => setShowCreateBranch(true)}>
                                        新建空分支
                                    </Button>
                                </div>
                            </div>

                            <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                                <Table
                                    columns={branchColumns}
                                    dataSource={branches || []}
                                    rowKey="id"
                                    pagination={false}
                                />
                            </div>
                        </section>
                    )}

                    {/* VIEW: MODEL USAGE & IMAGE LOGS */}
                    {activeView === 'usage' && (
                        <section>
                            <UsagePanel projectId={projectId} />
                        </section>
                    )}
                </>
            )}

            {/* MODAL: IMPORT EPISODE */}
            <Modal
                title="导入漫画章节 (图片或 ZIP)"
                visible={showImport}
                onCancel={() => {
                    setShowImport(false)
                    setUploadFiles([])
                }}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        const formValues = values as unknown as ImportFormValues
                        importMutation.mutate({
                            branch_id: formValues.branch_id || mainBranch?.id || '',
                            number: formValues.number,
                            label: formValues.label || String(formValues.number),
                            title: formValues.title,
                            category: formValues.category,
                            auto_understand: formValues.auto_understand,
                            files: uploadFiles,
                        })
                    }}
                    initValues={{
                        branch_id: selectedBranch || mainBranch?.id,
                        number: episodes.length > 0 ? Math.floor(episodes[episodes.length - 1].number) + 1 : 1,
                        auto_understand: true,
                    }}
                >
                    <Form.Select field="branch_id" label="所属分支" style={{ width: '100%' }}>
                        {branches?.map((b) => (
                            <Select.Option key={b.id} value={b.id}>
                                {b.name}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <div className="grid grid-cols-2 gap-3">
                        <Form.InputNumber
                            field="number"
                            label="排序序号"
                            min={0.01}
                            step={1}
                            style={{ width: '100%' }}
                            rules={[{ required: true }]}
                        />
                        <Form.Input field="label" label="展示话数 (如 12, 12.5, 番外1)" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <Form.Select field="category" label="章节分类" style={{ width: '100%' }} initValue="regular">
                            <Select.Option value="regular">正篇</Select.Option>
                            <Select.Option value="special">番外</Select.Option>
                            <Select.Option value="extra">加笔</Select.Option>
                        </Form.Select>
                        <Form.Input field="title" label="章节标题（可选）" />
                    </div>
                    <Form.Checkbox field="auto_understand" label="导入后立即执行多模态剧情理解（若一次导入多话，建议取消勾选后用「一键按序理解全书」）" />
                    <div className="mb-4">
                        <label className="block text-sm font-medium mb-1">漫画页面图片或单话 ZIP 压缩包</label>
                        <input
                            type="file"
                            multiple
                            accept="image/*,.zip"
                            onChange={(e) => e.target.files && setUploadFiles(Array.from(e.target.files))}
                            className="block w-full text-sm text-[var(--text-secondary)] file:mr-4 file:py-1.5 file:px-3 file:rounded-[4px] file:border file:border-[var(--border)] file:text-xs file:font-medium file:bg-[var(--bg-elevated)] file:text-[var(--text-primary)] hover:file:border-[var(--accent)]"
                        />
                        {uploadFiles.length > 0 && (
                            <div className="mt-1.5 text-xs text-[var(--accent)]">已选择 {uploadFiles.length} 个文件（将按文件名自然序排列页码）</div>
                        )}
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowImport(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={importMutation.isPending}>
                            开始导入
                        </Button>
                    </div>
                </Form>
            </Modal>

            {/* MODAL: CONTINUE GENERATION */}
            <Modal
                title="智能续画新章节（全自动闭环）"
                visible={showContinue}
                onCancel={() => setShowContinue(false)}
                footer={null}
                width={560}
            >
                <div className="space-y-4">
                    <Banner
                        type="info"
                        closeIcon={null}
                        description="将自动组装「主线脉络 + 上话结尾桥接 + 角色累积状态与原声样本 + 道具场景设定 + 未解伏笔」，依次执行：分镜编剧 → 一致性审校 → 参考图一致生图 → 气泡排版 → 记忆回写。"
                    />
                    <div>
                        <label className="block text-sm font-medium mb-1">接续自哪一话（严格截断未来剧透）</label>
                        <Select
                            value={continueForm.base_episode_id}
                            onChange={(v) => setContinueForm({ ...continueForm, base_episode_id: String(v || '') })}
                            style={{ width: '100%' }}
                            placeholder="选择基础章节"
                        >
                            {episodes.map((e: Episode) => (
                                <Select.Option key={e.id} value={e.id}>
                                    第 {e.label} 话 - {e.title || STATUS_META[e.status]?.label || e.status}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm font-medium mb-1">本话叙事基调</label>
                            <Select
                                value={continueForm.tone}
                                onChange={(v) => setContinueForm({ ...continueForm, tone: String(v || 'main') })}
                                style={{ width: '100%' }}
                            >
                                <Select.Option value="main">主线推进 (Main Plot)</Select.Option>
                                <Select.Option value="pit_resolve">伏笔回收揭秘 (Resolve Pit)</Select.Option>
                                <Select.Option value="climax">高潮决战 / 转折 (Climax)</Select.Option>
                                <Select.Option value="daily">日常互动 / 羁绊升温 (Daily)</Select.Option>
                                <Select.Option value="filler">支线过渡章 (Side Story)</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1">上下文预算策略</label>
                            <Select
                                value={continueForm.context_profile}
                                onChange={(v) =>
                                    setContinueForm({
                                        ...continueForm,
                                        context_profile: (v as 'quality' | 'balanced' | 'cost') || 'quality',
                                    })
                                }
                                style={{ width: '100%' }}
                            >
                                <Select.Option value="quality">效果优先 · 200K+ (64K 预算)</Select.Option>
                                <Select.Option value="balanced">均衡模式 · 128K (28K 预算)</Select.Option>
                                <Select.Option value="cost">成本优先 · 32K (10K 预算)</Select.Option>
                            </Select>
                        </div>
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">自定义新话标题（可选）</label>
                        <Input
                            value={continueForm.title}
                            onChange={(v) => setContinueForm({ ...continueForm, title: v })}
                            placeholder="留空则由编剧模型自动拟定"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">导演剧情指令（可选）</label>
                        <TextArea
                            value={continueForm.custom_instructions}
                            onChange={(v) => setContinueForm({ ...continueForm, custom_instructions: v })}
                            placeholder="例如：本话让小樱和阿明解读爷爷留下的发光信件，揭示星之匣真正的来历，结尾引出新的神秘人物..."
                            rows={3}
                        />
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                        <div>
                            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">生图引擎</label>
                            <Select
                                value={continueForm.image_backend}
                                onChange={(v) => setContinueForm({ ...continueForm, image_backend: v ? String(v) : undefined })}
                                style={{ width: '100%' }}
                                placeholder="默认配置"
                            >
                                <Select.Option value="antigravity">Antigravity (原生生图)</Select.Option>
                                <Select.Option value="openai">OpenAI (GPT-Image)</Select.Option>
                                <Select.Option value="gemini">Gemini (Nano Banana)</Select.Option>
                                <Select.Option value="custom">Custom HTTP</Select.Option>
                                <Select.Option value="mock">Mock 预览模式</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">生图模型</label>
                            <Select
                                value={continueForm.image_model}
                                onChange={(v) => setContinueForm({ ...continueForm, image_model: v ? String(v) : undefined })}
                                style={{ width: '100%' }}
                                placeholder="默认模型"
                            >
                                <Select.Option value="gpt-image-2">gpt-image-2</Select.Option>
                                <Select.Option value="gemini-3.1-flash-image">gemini-3.1-flash-image (NB2)</Select.Option>
                                <Select.Option value="gemini-3-pro-image">gemini-3-pro-image</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">单格画幅</label>
                            <Select
                                value={continueForm.image_size}
                                onChange={(v) => setContinueForm({ ...continueForm, image_size: String(v || '1024x1024') })}
                                style={{ width: '100%' }}
                            >
                                <Select.Option value="1024x1024">1024x1024</Select.Option>
                                <Select.Option value="1024x1536">1024x1536 (竖构图)</Select.Option>
                                <Select.Option value="1536x1024">1536x1024 (横构图)</Select.Option>
                            </Select>
                        </div>
                    </div>
                    <div className="flex justify-end gap-2 pt-2">
                        <Button onClick={() => setShowContinue(false)}>取消</Button>
                        <Button
                            theme="solid"
                            loading={continueMutation.isPending}
                            disabled={!continueForm.base_episode_id}
                            onClick={() => continueMutation.mutate()}
                        >
                            启动续画创作
                        </Button>
                    </div>
                </div>
            </Modal>

            {/* MODAL: CREATE PIT */}
            <Modal title="手动埋设伏笔" visible={showCreatePit} onCancel={() => setShowCreatePit(false)} footer={null}>
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createPitMutation.mutate({
                            title: String(values.title || ''),
                            description: values.description ? String(values.description) : undefined,
                            priority: values.priority ? Number(values.priority) : 5,
                            introduced_episode_id: String(values.introduced_episode_id || ''),
                            trigger_hint: values.trigger_hint ? String(values.trigger_hint) : undefined,
                        })
                    }}
                    initValues={{ priority: 8, introduced_episode_id: episodes[episodes.length - 1]?.id }}
                >
                    <Form.Input field="title" label="伏笔简述标题" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="详细悬念说明" rows={3} />
                    <Form.InputNumber field="priority" label="重要度 (0-10，≥8 为核心主线)" min={0} max={10} />
                    <Form.Select field="introduced_episode_id" label="埋设章节" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {episodes.map((e: Episode) => (
                            <Select.Option key={e.id} value={e.id}>
                                第 {e.label} 话 - {e.title || e.status}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="trigger_hint" label="回收触发时机提示（可选）" />
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowCreatePit(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={createPitMutation.isPending}>
                            保存伏笔
                        </Button>
                    </div>
                </Form>
            </Modal>

            {/* MODAL: RESOLVE PIT */}
            <Modal
                title="标记伏笔回收"
                visible={showResolvePit}
                onCancel={() => {
                    setShowResolvePit(false)
                    setResolvingPit(null)
                }}
                footer={null}
            >
                {resolvingPit && (
                    <Form
                        onSubmit={(values: Record<string, unknown>) => {
                            resolvePitMutation.mutate({
                                pitId: resolvingPit.id,
                                resolvedEpisodeId: String(values.resolved_episode_id || ''),
                            })
                        }}
                        initValues={{ resolved_episode_id: episodes[episodes.length - 1]?.id }}
                    >
                        <div className="mb-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                            <div className="font-bold text-slate-900 mb-1">{resolvingPit.title}</div>
                            <div>{resolvingPit.description}</div>
                        </div>
                        <Form.Select field="resolved_episode_id" label="在哪一话完成回收" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {episodes.map((e: Episode) => (
                                <Select.Option key={e.id} value={e.id}>
                                    第 {e.label} 话 - {e.title || e.status}
                                </Select.Option>
                            ))}
                        </Form.Select>
                        <div className="flex justify-end gap-2 mt-4">
                            <Button onClick={() => setShowResolvePit(false)}>取消</Button>
                            <Button htmlType="submit" theme="solid" loading={resolvePitMutation.isPending}>
                                确认已回收
                            </Button>
                        </div>
                    </Form>
                )}
            </Modal>

            {/* MODAL: ASSET IMAGES */}
            <Modal
                title={`视觉参考锚点 · ${imageAsset?.name || ''}`}
                visible={!!imageAsset}
                onCancel={() => setImageAsset(null)}
                footer={null}
                width={700}
            >
                <div className="flex flex-wrap items-center gap-3 mb-4">
                    <Select value={uploadImageKind} onChange={(v) => setUploadImageKind(String(v))} style={{ width: 170 }}>
                        <Select.Option value="reference">标准设定图 (优先)</Select.Option>
                        <Select.Option value="turnaround">多视角三视图</Select.Option>
                        <Select.Option value="thumbnail">漫画原画截框</Select.Option>
                        <Select.Option value="lora_dataset">训练集素材</Select.Option>
                    </Select>
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        hidden
                        onChange={(e) => {
                            const f = e.target.files?.[0]
                            if (f) uploadImageMutation.mutate(f)
                            e.target.value = ''
                        }}
                    />
                    <Button
                        icon={<IconPlus />}
                        theme="solid"
                        loading={uploadImageMutation.isPending}
                        onClick={() => fileInputRef.current?.click()}
                    >
                        上传高清参考图
                    </Button>
                    <span className="text-xs text-[var(--text-muted)]">同时用于多模态人脸匹配与生图角色一致性锚定</span>
                </div>

                {assetImagesLoading ? (
                    <Spin />
                ) : (assetImagesData?.items || []).length === 0 ? (
                    <Empty description="暂无参考图，可上传角色立绘或漫画截图" />
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        {(assetImagesData?.items || []).map((img, idx) => {
                            const isPrimary = Boolean((img.meta as Record<string, unknown> | undefined)?.is_primary) || (idx === 0 && img.kind === 'reference')
                            const score = (img.meta as Record<string, unknown> | undefined)?.portrait_score
                            return (
                                <div
                                    key={img.id}
                                    className="rounded-[6px] p-2.5 space-y-2 bg-[var(--bg-panel)] border"
                                    style={{ borderColor: isPrimary ? 'var(--accent)' : 'var(--border)' }}
                                >
                                    <div className="w-full h-36 rounded-[4px] overflow-hidden flex items-center justify-center bg-[var(--bg-canvas)]">
                                        <img
                                            src={storageFileUrl(img.image_path)}
                                            alt={img.kind}
                                            className="max-w-full max-h-full object-contain"
                                        />
                                    </div>
                                    <div className="flex items-center justify-between gap-1.5">
                                        <div className="flex items-center gap-1.5 shrink-0">
                                            <Tag size="small" color={isPrimary ? 'red' : img.kind === 'reference' ? 'indigo' : 'grey'}>
                                                {isPrimary
                                                    ? '主头像'
                                                    : img.kind === 'reference'
                                                      ? '设定图'
                                                      : img.kind === 'turnaround'
                                                        ? '三视图'
                                                        : '候选图'}
                                            </Tag>
                                            {typeof score === 'number' && score > 0 && (
                                                <span className="font-mono text-[11px] text-[var(--text-muted)] whitespace-nowrap">
                                                    {score.toFixed(1)}
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-0.5 shrink-0">
                                            {!isPrimary && (
                                                <Button
                                                    size="small"
                                                    theme="borderless"
                                                    loading={setPrimaryImageMutation.isPending}
                                                    onClick={() => setPrimaryImageMutation.mutate(img.id)}
                                                >
                                                    设为主图
                                                </Button>
                                            )}
                                            <Button
                                                size="small"
                                                type="danger"
                                                theme="borderless"
                                                icon={<IconDelete />}
                                                loading={deleteImageMutation.isPending}
                                                onClick={() => deleteImageMutation.mutate(img.id)}
                                            />
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </Modal>

            {/* MODAL: CREATE / EDIT / MERGE / SIMILAR / CLUSTER ASSETS */}
            <Modal title="手动新增视觉资产" visible={showCreateAsset} onCancel={() => setShowCreateAsset(false)} footer={null}>
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createAssetMutation.mutate({
                            type: String(values.type || 'character'),
                            name: String(values.name || ''),
                            description: values.description ? String(values.description) : undefined,
                            visual_tags: values.visual_tags ? String(values.visual_tags) : undefined,
                        })
                    }}
                    initValues={{ type: 'character' }}
                >
                    <Form.Select field="type" label="资产类型" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {ASSET_TYPE_OPTIONS.map((opt) => (
                            <Select.Option key={opt.value} value={opt.value}>
                                {opt.label}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="name" label="名称" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="外貌 / 材质 / 场景视觉细节描述" rows={4} />
                    <Form.Input field="visual_tags" label="英文视觉 Prompt 标签（逗号分隔，可选）" placeholder="pink twin-tails, blue sailor uniform, star-shaped key" />
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowCreateAsset(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={createAssetMutation.isPending}>
                            创建资产
                        </Button>
                    </div>
                </Form>
            </Modal>

            <Modal title="编辑资产设定" visible={!!editingAsset} onCancel={() => setEditingAsset(null)} footer={null}>
                {editingAsset && (
                    <Form
                        onSubmit={(values: Record<string, unknown>) => {
                            const vtags = String(values.visual_tags || '')
                                .split(/[,，]/)
                                .map((s) => s.trim())
                                .filter(Boolean)
                            updateAssetMutation.mutate({
                                assetId: editingAsset.id,
                                updates: {
                                    name: String(values.name || ''),
                                    description: values.description ? String(values.description) : undefined,
                                    tags: {
                                        ...(editingAsset.tags || {}),
                                        visual_tags: vtags,
                                        speech_style: values.speech_style ? String(values.speech_style) : editingAsset.tags?.speech_style,
                                    },
                                },
                            })
                        }}
                        initValues={{
                            name: editingAsset.name,
                            description: editingAsset.description || '',
                            visual_tags: (editingAsset.tags?.visual_tags || []).join(', '),
                            speech_style: editingAsset.tags?.speech_style || '',
                        }}
                    >
                        <Form.Input field="name" label="名称" rules={[{ required: true }]} />
                        <Form.TextArea field="description" label="视觉与背景描述" rows={4} />
                        <Form.Input field="visual_tags" label="英文视觉标签（逗号分隔）" />
                        {editingAsset.type === 'character' && (
                            <Form.Input field="speech_style" label="角色说话语气 / 口癖特征" />
                        )}
                        <div className="flex justify-end gap-2 mt-4">
                            <Button onClick={() => setEditingAsset(null)}>取消</Button>
                            <Button htmlType="submit" theme="solid" loading={updateAssetMutation.isPending}>
                                保存修改
                            </Button>
                        </div>
                    </Form>
                )}
            </Modal>

            <Modal
                title={`合并选中的 ${selectedAssetIds.length} 项资产`}
                visible={showAssetMerge}
                onCancel={() => setShowAssetMerge(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        assetMergeMutation.mutate({
                            source_asset_ids: selectedAssetIds,
                            target_name: String(values.target_name || ''),
                            target_description: values.target_description ? String(values.target_description) : undefined,
                        })
                    }}
                >
                    <Form.Input field="target_name" label="合并后的标准名称" rules={[{ required: true }]} />
                    <Form.TextArea field="target_description" label="合并后描述（留空则自动拼接保留全部细节）" rows={3} />
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowAssetMerge(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={assetMergeMutation.isPending}>
                            执行合并
                        </Button>
                    </div>
                </Form>
            </Modal>

            <Modal title="相似资产检索结果" visible={showSimilar} onCancel={() => setShowSimilar(false)} footer={null}>
                {similarAssets.length === 0 ? (
                    <Empty description="未找到其他相似资产" />
                ) : (
                    <Table
                        dataSource={similarAssets}
                        rowKey="asset_id"
                        pagination={false}
                        size="small"
                        columns={[
                            { title: '名称', dataIndex: 'name', key: 'name' },
                            { title: '类型', dataIndex: 'asset_type', key: 'asset_type', width: 90 },
                            {
                                title: '相似度',
                                dataIndex: 'similarity',
                                key: 'similarity',
                                width: 100,
                                render: (v: number) => `${(v * 100).toFixed(1)}%`,
                            },
                        ]}
                    />
                )}
            </Modal>

            <Modal
                title="资产相似聚类结果"
                visible={showClusterResult}
                onCancel={() => setShowClusterResult(false)}
                footer={null}
                width={720}
            >
                {clusterData && (
                    <div className="space-y-4">
                        <Descriptions
                            row
                            data={[
                                { key: '总资产数', value: String(clusterData.total_assets) },
                                { key: '潜在重复簇', value: String(clusterData.clusters.length) },
                                { key: '独立资产', value: String(clusterData.unclustered) },
                            ]}
                        />
                        {clusterData.clusters.length === 0 ? (
                            <Empty description="当前资产命名清晰，未发现重复簇" />
                        ) : (
                            clusterData.clusters.map((group, idx) => (
                                <div key={idx} className="border border-slate-200 rounded-xl p-3 space-y-2">
                                    <div className="flex items-center justify-between">
                                        <span className="font-bold text-sm">{group.representative_name}</span>
                                        <Button
                                            size="small"
                                            theme="light"
                                            onClick={() => {
                                                setSelectedAssetIds(group.items.map((it) => it.asset_id))
                                                setShowClusterResult(false)
                                                setShowAssetMerge(true)
                                            }}
                                        >
                                            一键合并此簇
                                        </Button>
                                    </div>
                                    <div className="flex flex-wrap gap-1.5">
                                        {group.items.map((it) => (
                                            <Tag key={it.asset_id}>
                                                {it.name} ({(it.similarity * 100).toFixed(0)}%)
                                            </Tag>
                                        ))}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                )}
            </Modal>

            {/* BRANCH MODALS: CREATE / FORK / DIFF / MERGE */}
            <Modal title="新建平行分支" visible={showCreateBranch} onCancel={() => setShowCreateBranch(false)} footer={null}>
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createBranchMutation.mutate({
                            name: String(values.name || ''),
                            description: values.description ? String(values.description) : undefined,
                        })
                    }}
                >
                    <Form.Input field="name" label="分支名称" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="分支剧情走向备注（可选）" />
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowCreateBranch(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={createBranchMutation.isPending}>
                            创建分支
                        </Button>
                    </div>
                </Form>
            </Modal>

            <Modal title="从指定章节派生 IF 世界线 (Fork)" visible={showFork} onCancel={() => setShowFork(false)} footer={null}>
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        forkMutation.mutate({
                            episode_id: String(values.episode_id || ''),
                            branch_name: String(values.branch_name || ''),
                            description: values.description ? String(values.description) : undefined,
                        })
                    }}
                >
                    <Form.Select field="episode_id" label="分叉起点章节（将完整克隆该话及之前的记忆与页面）" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {episodes.map((e: Episode) => (
                            <Select.Option key={e.id} value={e.id}>
                                第 {e.label} 话 - {e.title || e.status}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="branch_name" label="新世界线名称" placeholder="例如：if-route-keep-box-sealed" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="IF 线构想说明（可选）" />
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowFork(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={forkMutation.isPending}>
                            确认派生分支
                        </Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="对比分支差异 (Diff)"
                visible={showDiff}
                onCancel={() => {
                    setShowDiff(false)
                    setDiffResult(null)
                }}
                footer={null}
                width={860}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        diffMutation.mutate({
                            source_branch_id: String(values.source_branch_id || ''),
                            target_branch_id: String(values.target_branch_id || ''),
                        })
                    }}
                >
                    <div className="grid grid-cols-2 gap-4">
                        <Form.Select field="source_branch_id" label="源分支 (Source)" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {branches?.map((b) => (
                                <Select.Option key={b.id} value={b.id}>
                                    {b.name}
                                </Select.Option>
                            ))}
                        </Form.Select>
                        <Form.Select field="target_branch_id" label="目标分支 (Target)" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {branches?.map((b) => (
                                <Select.Option key={b.id} value={b.id}>
                                    {b.name}
                                </Select.Option>
                            ))}
                        </Form.Select>
                    </div>
                    <div className="flex justify-end gap-2 mt-3">
                        <Button htmlType="submit" theme="solid" loading={diffMutation.isPending}>
                            对比差异
                        </Button>
                    </div>
                </Form>
                {diffResult && (
                    <div className="space-y-4 mt-4 max-h-96 overflow-y-auto">
                        <Table
                            size="small"
                            pagination={false}
                            dataSource={diffResult.episodes}
                            rowKey={(r?: { number: number }) => String(r?.number ?? '')}
                            columns={[
                                { title: '话数', dataIndex: 'label', key: 'label', width: 80 },
                                { title: '源分支标题', dataIndex: 'title_source', key: 'title_source', render: (t: string | null) => t || '-' },
                                { title: '目标分支标题', dataIndex: 'title_target', key: 'title_target', render: (t: string | null) => t || '-' },
                                { title: '源状态', dataIndex: 'source_status', key: 'source_status', width: 100, render: (t: string | null) => t || '无' },
                                { title: '目标状态', dataIndex: 'target_status', key: 'target_status', width: 100, render: (t: string | null) => t || '无' },
                            ]}
                        />
                    </div>
                )}
            </Modal>

            <Modal
                title="合并分支成果 (Merge)"
                visible={showMerge}
                onCancel={() => {
                    setShowMerge(false)
                    setDiffResult(null)
                    setMergeItems([])
                }}
                footer={null}
                width={820}
            >
                {!diffResult ? (
                    <Form
                        onSubmit={(values: Record<string, unknown>) => {
                            handleDiffForMerge(String(values.source_branch_id || ''), String(values.target_branch_id || ''))
                        }}
                    >
                        <div className="grid grid-cols-2 gap-4">
                            <Form.Select field="source_branch_id" label="从哪个分支合并 (Source)" style={{ width: '100%' }} rules={[{ required: true }]}>
                                {branches?.map((b) => (
                                    <Select.Option key={b.id} value={b.id}>
                                        {b.name}
                                    </Select.Option>
                                ))}
                            </Form.Select>
                            <Form.Select field="target_branch_id" label="合并入目标分支 (Target)" style={{ width: '100%' }} rules={[{ required: true }]}>
                                {branches?.map((b) => (
                                    <Select.Option key={b.id} value={b.id}>
                                        {b.name}
                                    </Select.Option>
                                ))}
                            </Form.Select>
                        </div>
                        <div className="flex justify-end gap-2 mt-4">
                            <Button onClick={() => setShowMerge(false)}>取消</Button>
                            <Button htmlType="submit" theme="solid" loading={diffMutation.isPending}>
                                分析可合并条目
                            </Button>
                        </div>
                    </Form>
                ) : (
                    <div className="space-y-4">
                        {mergeItems.length === 0 ? (
                            <Empty description="源分支没有目标分支缺失的新增章节、资产或伏笔" />
                        ) : (
                            <Table
                                size="small"
                                pagination={false}
                                dataSource={mergeItems}
                                rowKey={(r?: MergeItem) => `${r?.item_type}-${r?.source_id}`}
                                columns={[
                                    { title: '类型', dataIndex: 'item_type', key: 'item_type', width: 100 },
                                    { title: '条目 ID', dataIndex: 'source_id', key: 'source_id' },
                                    {
                                        title: '决策',
                                        dataIndex: 'action',
                                        key: 'action',
                                        width: 180,
                                        render: (action: string, _r: MergeItem, index: number) => (
                                            <RadioGroup
                                                type="button"
                                                value={action}
                                                options={[
                                                    { label: '采纳', value: 'adopt' },
                                                    { label: '跳过', value: 'skip' },
                                                ]}
                                                onChange={(e) => {
                                                    const next = [...mergeItems]
                                                    next[index] = { ...next[index], action: e.target.value as 'adopt' | 'skip' }
                                                    setMergeItems(next)
                                                }}
                                            />
                                        ),
                                    },
                                ]}
                            />
                        )}
                        <div className="flex justify-end gap-2">
                            <Button onClick={() => setShowMerge(false)}>取消</Button>
                            <Button
                                theme="solid"
                                disabled={mergeItems.length === 0}
                                loading={mergeMutation.isPending}
                                onClick={() =>
                                    mergeMutation.mutate({
                                        source_branch_id: mergeSourceBranch,
                                        target_branch_id: mergeTargetBranch,
                                        items: mergeItems,
                                    })
                                }
                            >
                                确认合并 ({mergeItems.filter((i) => i.action === 'adopt').length} 项)
                            </Button>
                        </div>
                    </div>
                )}
            </Modal>
        </div>
    )
}
