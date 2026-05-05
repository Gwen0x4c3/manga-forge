import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Tabs, TabPane, Typography, Spin, Button, Table, Tag, Modal, Form, Select, Toast, Empty, Input, TextArea, Descriptions, Checkbox, RadioGroup } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus, IconForward, IconDelete, IconCopy, IconRefresh, IconSearch, IconLink } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService, branchService, episodeService, memoryService, generationService, pitService, assetService } from '@/services/project'
import type { Episode, Pit, Branch, DiffResponse, MergeItem, Asset, AssetClusterResponse, AssetClusterItem } from '@/services/project'

const { Title, Paragraph } = Typography

const STATUS_COLORS: Record<string, TagColor> = {
    imported: 'blue',
    understood: 'cyan',
    scripted: 'green',
    rendered: 'orange',
    published: 'purple',
    draft: 'grey',
    generating: 'violet',
}

const PIT_STATUS_COLORS: Record<string, TagColor> = {
    open: 'blue',
    resolved: 'green',
    abandoned: 'grey',
}

const CATEGORY_LABELS: Record<string, { text: string; color: TagColor }> = {
    regular: { text: '正篇', color: 'blue' },
    special: { text: '番外', color: 'orange' },
    extra: { text: '加笔', color: 'purple' },
}

const ASSET_TYPE_OPTIONS = [
    { value: 'character', label: '角色' },
    { value: 'outfit', label: '服装' },
    { value: 'location', label: '场景' },
    { value: 'item', label: '道具' },
    { value: 'style', label: '风格' },
]

const ASSET_TYPE_COLORS: Record<string, TagColor> = {
    character: 'blue',
    outfit: 'purple',
    location: 'green',
    item: 'orange',
    style: 'cyan',
}

interface ImportFormValues {
    branch_id: string
    number: number
    label?: string
    title?: string
    category?: string
}

export default function ProjectDetail() {
    const { id: projectId } = useParams<{ id: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [showImport, setShowImport] = useState(false)
    const [showContinue, setShowContinue] = useState(false)
    const [showCreatePit, setShowCreatePit] = useState(false)
    const [showResolvePit, setShowResolvePit] = useState(false)
    const [resolvingPit, setResolvingPit] = useState<Pit | null>(null)
    const [selectedBranch, setSelectedBranch] = useState<string | undefined>()
    const [uploadFiles, setUploadFiles] = useState<File[]>([])
    const [canonRules, setCanonRules] = useState<Record<string, unknown>>({})
    const [canonValid, setCanonValid] = useState(true)
    const [ragQuery, setRagQuery] = useState('')
    const [ragResults, setRagResults] = useState<Array<{ score: number; payload: Record<string, unknown> }>>([])
    const [pitStatusFilter, setPitStatusFilter] = useState<string | undefined>('open')
    const [continueForm, setContinueForm] = useState({
        base_episode_id: '',
        tone: 'main',
        custom_instructions: '',
        title: '',
        image_backend: undefined as string | undefined,
        image_model: undefined as string | undefined,
        image_size: undefined as string | undefined,
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
    const [showCreateAsset, setShowCreateAsset] = useState(false)
    const [editingAsset, setEditingAsset] = useState<Asset | null>(null)
    const [showClusterResult, setShowClusterResult] = useState(false)
    const [clusterData, setClusterData] = useState<AssetClusterResponse | null>(null)
    const [showSimilar, setShowSimilar] = useState(false)
    const [similarAssets, setSimilarAssets] = useState<AssetClusterItem[]>([])
    const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
    const [showAssetMerge, setShowAssetMerge] = useState(false)

    const [episodePage, setEpisodePage] = useState(1)
    const [episodePageSize, setEpisodePageSize] = useState(50)
    const [assetPage, setAssetPage] = useState(1)
    const [assetPageSize, setAssetPageSize] = useState(50)
    const [pitPage, setPitPage] = useState(1)
    const [pitPageSize, setPitPageSize] = useState(50)

    const { data: project, isLoading: projectLoading } = useQuery({
        queryKey: ['project', projectId],
        queryFn: () => projectService.get(projectId!),
        enabled: !!projectId,
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
    })

    const { data: pitsData, isLoading: pitsLoading } = useQuery({
        queryKey: ['pits', projectId, pitStatusFilter, pitPage, pitPageSize],
        queryFn: () => pitService.list(projectId!, pitStatusFilter, { page: pitPage, page_size: pitPageSize }),
        enabled: !!projectId,
    })

    const { data: assetsData, isLoading: assetsLoading } = useQuery({
        queryKey: ['assets', projectId, assetTypeFilter, assetPage, assetPageSize],
        queryFn: () => assetService.list(projectId!, assetTypeFilter, { page: assetPage, page_size: assetPageSize }),
        enabled: !!projectId,
    })

    const mainBranch = branches?.find((b) => b.name === 'main')

    const importMutation = useMutation({
        mutationFn: async (data: { branch_id: string; number: number; label?: string; title?: string; category?: string; files: File[] }) => {
            const formData = new FormData()
            formData.append('branch_id', data.branch_id)
            formData.append('number', String(data.number))
            if (data.label) formData.append('label', data.label)
            if (data.title) formData.append('title', data.title)
            if (data.category) formData.append('category', data.category)
            data.files.forEach((f) => formData.append('files', f))
            return episodeService.importFiles(projectId!, formData)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowImport(false)
            setUploadFiles([])
            Toast.success('Episode imported')
        },
        onError: () => {},
    })

    const continueMutation = useMutation({
        mutationFn: () => {
            const baseEpisode = episodesData?.items?.find((e: Episode) => e.id === continueForm.base_episode_id)
            if (!baseEpisode) return Promise.reject(new Error('No base episode selected'))
            return generationService.triggerContinue({
                project_id: projectId!,
                branch_id: baseEpisode.branch_id,
                base_episode_number: baseEpisode.number,
                tone: continueForm.tone,
                custom_instructions: continueForm.custom_instructions || undefined,
                title: continueForm.title || undefined,
                image_backend: continueForm.image_backend,
                image_model: continueForm.image_model,
                image_size: continueForm.image_size,
            })
        },
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowContinue(false)
            Toast.success('Continue generation started')
            navigate(`/projects/${projectId}/episodes/${data.episode_id}/generate`)
        },
        onError: () => {},
    })

    const createPitMutation = useMutation({
        mutationFn: (data: { title: string; description?: string; priority?: number; introduced_episode_id: string; trigger_hint?: string }) =>
            pitService.create(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pits', projectId] })
            setShowCreatePit(false)
            Toast.success('Pit created')
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
            Toast.success('Pit resolved')
        },
        onError: () => {},
    })

    const deleteEpisodeMutation = useMutation({
        mutationFn: (episodeId: string) => episodeService.delete(episodeId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            Toast.success('Episode deleted')
        },
        onError: () => {},
    })

    const createBranchMutation = useMutation({
        mutationFn: (data: { name: string; description?: string }) => branchService.create(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            setShowCreateBranch(false)
            Toast.success('Branch created')
        },
        onError: () => {},
    })

    const deleteBranchMutation = useMutation({
        mutationFn: (branchId: string) => branchService.delete(branchId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            Toast.success('Branch deleted')
        },
        onError: () => {},
    })

    const forkMutation = useMutation({
        mutationFn: (data: { episode_id: string; branch_name: string; description?: string }) => branchService.fork(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowFork(false)
            Toast.success('Branch forked')
        },
        onError: () => {},
    })

    const diffMutation = useMutation({
        mutationFn: (data: { source_branch_id: string; target_branch_id: string; episode_number?: number }) => branchService.diff(projectId!, data),
        onSuccess: (data) => {
            setDiffResult(data)
            Toast.success('Diff completed')
        },
        onError: () => {},
    })

    const mergeMutation = useMutation({
        mutationFn: (data: { source_branch_id: string; target_branch_id: string; items: MergeItem[] }) => branchService.merge(projectId!, data),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['branches', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowMerge(false)
            setDiffResult(null)
            setMergeItems([])
            setMergeSourceBranch('')
            setMergeTargetBranch('')
            if (data.errors.length > 0) {
                Toast.warning(`Merged ${data.merged_items.length}, skipped ${data.skipped_items.length}, errors: ${data.errors.join(', ')}`)
            } else {
                Toast.success(`Merged ${data.merged_items.length} items, skipped ${data.skipped_items.length}`)
            }
        },
        onError: () => {},
    })

    const createAssetMutation = useMutation({
        mutationFn: (data: { type: string; name: string; description?: string }) => assetService.create(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setShowCreateAsset(false)
            Toast.success('Asset created')
        },
        onError: () => {},
    })

    const updateAssetMutation = useMutation({
        mutationFn: (data: { assetId: string; updates: { name?: string; description?: string } }) => assetService.update(data.assetId, data.updates),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setEditingAsset(null)
            Toast.success('Asset updated')
        },
        onError: () => {},
    })

    const deleteAssetMutation = useMutation({
        mutationFn: (assetId: string) => assetService.delete(assetId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            Toast.success('Asset deleted')
        },
        onError: () => {},
    })

    const clusterMutation = useMutation({
        mutationFn: () => assetService.cluster(projectId!, assetTypeFilter),
        onSuccess: (data) => {
            setClusterData(data)
            setShowClusterResult(true)
            Toast.success('Clustering completed')
        },
        onError: () => {},
    })

    const assetMergeMutation = useMutation({
        mutationFn: (data: { source_asset_ids: string[]; target_name: string; target_description?: string }) => assetService.merge(projectId!, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
            setShowAssetMerge(false)
            setSelectedAssetIds([])
            Toast.success('Assets merged')
        },
        onError: () => {},
    })

    const vectorizeMutation = useMutation({
        mutationFn: (assetId: string) => assetService.vectorize(assetId),
        onSuccess: () => {
            Toast.success('Asset vectorized')
        },
        onError: () => {},
    })

    if (projectLoading) return <Spin size="large" />
    if (!project) return <Empty description="Project not found" />

    const episodeColumns = [
        { title: '#', dataIndex: 'label', key: 'label', width: 80 },
        { title: 'Title', dataIndex: 'title', key: 'title', render: (text: string) => text || '-' },
        {
            title: 'Category',
            dataIndex: 'category',
            key: 'category',
            width: 80,
            render: (text: string) => {
                const cat = CATEGORY_LABELS[text]
                return cat ? <Tag color={cat.color}>{cat.text}</Tag> : <Tag>{text}</Tag>
            },
        },
        { title: 'Source', dataIndex: 'source', key: 'source', render: (text: string) => <Tag>{text}</Tag> },
        {
            title: 'Status',
            dataIndex: 'status',
            key: 'status',
            render: (text: string) => <Tag color={STATUS_COLORS[text] || 'default' as TagColor}>{text}</Tag>,
        },
        {
            title: 'Updated',
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: (text: string) => new Date(text).toLocaleDateString(),
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: unknown, record: Episode) => (
                <div className="flex gap-1">
                    <Button size="small" onClick={() => navigate(`/projects/${projectId}/episodes/${record.id}`)}>
                        View
                    </Button>
                    <Button
                        size="small"
                        type="danger"
                        icon={<IconDelete />}
                        loading={deleteEpisodeMutation.isPending}
                        onClick={() => {
                            Modal.confirm({
                                title: 'Delete Episode',
                                content: `Are you sure you want to delete "${record.label} - ${record.title || record.status}"? This action cannot be undone.`,
                                onOk: () => deleteEpisodeMutation.mutate(record.id),
                            })
                        }}
                    />
                </div>
            ),
        },
    ]

    const pitColumns = [
        { title: 'Title', dataIndex: 'title', key: 'title' },
        { title: 'Priority', dataIndex: 'priority', key: 'priority', width: 80 },
        {
            title: 'Status',
            dataIndex: 'status',
            key: 'status',
            width: 100,
            render: (text: string) => <Tag color={PIT_STATUS_COLORS[text] || ('default' as TagColor)}>{text}</Tag>,
        },
        {
            title: 'Introduced Episode',
            dataIndex: 'introduced_episode_id',
            key: 'introduced_episode_id',
            width: 160,
            render: (text: string) => <Button size="small" onClick={() => navigate(`/projects/${projectId}/episodes/${text}`)}>View Episode</Button>,
        },
        {
            title: 'Trigger Hint',
            dataIndex: 'trigger_hint',
            key: 'trigger_hint',
            render: (text: string) => text || '-',
        },
        {
            title: 'Actions',
            key: 'actions',
            width: 100,
            render: (_: unknown, record: Pit) => (
                record.status === 'open' ? (
                    <Button size="small" theme="solid" onClick={() => { setResolvingPit(record); setShowResolvePit(true) }}>
                        Resolve
                    </Button>
                ) : null
            ),
        },
    ]

    const branchColumns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (text: string, record: Branch) => (
                <span className="flex items-center gap-2">
                    {text}
                    {record.is_default && <Tag color="green" size="small">Default</Tag>}
                </span>
            ),
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            render: (text: string) => text || '-',
        },
        {
            title: 'Episodes',
            dataIndex: 'episode_count',
            key: 'episode_count',
            width: 90,
            render: (text: number) => text ?? '-',
        },
        {
            title: 'Latest Episode',
            dataIndex: 'latest_episode_number',
            key: 'latest_episode_number',
            width: 120,
            render: (text: number | null) => text != null ? String(text) : '-',
        },
        {
            title: 'Base Branch',
            dataIndex: 'base_branch_id',
            key: 'base_branch_id',
            width: 120,
            render: (text: string) => {
                if (!text) return '-'
                const baseBranch = branches?.find((b) => b.id === text)
                return baseBranch ? <Tag>{baseBranch.name}</Tag> : text
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
            width: 110,
            render: (t: string) => new Date(t).toLocaleDateString(),
        },
        {
            title: 'Actions',
            key: 'actions',
            width: 80,
            render: (_: unknown, record: Branch) => (
                !record.is_default ? (
                    <Button
                        size="small"
                        type="danger"
                        icon={<IconDelete />}
                        loading={deleteBranchMutation.isPending}
                        onClick={() => {
                            Modal.confirm({
                                title: 'Delete Branch',
                                content: `Are you sure you want to delete branch "${record.name}"? This action cannot be undone.`,
                                onOk: () => deleteBranchMutation.mutate(record.id),
                            })
                        }}
                    />
                ) : null
            ),
        },
    ]

    const assetColumns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: 'Type',
            dataIndex: 'type',
            key: 'type',
            width: 100,
            render: (text: string) => <Tag color={ASSET_TYPE_COLORS[text] || ('default' as TagColor)}>{text}</Tag>,
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            render: (text: string) => text || '-',
        },
        {
            title: 'Tags',
            dataIndex: 'tags',
            key: 'tags',
            width: 150,
            render: (tags: Record<string, unknown> | null) => {
                if (!tags || Object.keys(tags).length === 0) return '-'
                return (
                    <div className="flex flex-wrap gap-1">
                        {Object.entries(tags).slice(0, 3).map(([k, v]) => (
                            <Tag key={k} size="small">{k}: {String(v)}</Tag>
                        ))}
                        {Object.keys(tags).length > 3 && <Tag size="small">+{Object.keys(tags).length - 3}</Tag>}
                    </div>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
            width: 110,
            render: (t: string) => new Date(t).toLocaleDateString(),
        },
        {
            title: 'Actions',
            key: 'actions',
            width: 220,
            render: (_: unknown, record: Asset) => (
                <div className="flex gap-1">
                    <Button size="small" onClick={() => setEditingAsset(record)}>Edit</Button>
                    <Button size="small" icon={<IconSearch />} onClick={() => {
                        assetService.findSimilar(record.id).then((data) => {
                            setSimilarAssets(data)
                            setShowSimilar(true)
                        }).catch(() => {})
                    }}>Similar</Button>
                    <Button size="small" icon={<IconRefresh />} loading={vectorizeMutation.isPending} onClick={() => vectorizeMutation.mutate(record.id)} />
                    <Button
                        size="small"
                        type="danger"
                        icon={<IconDelete />}
                        onClick={() => {
                            Modal.confirm({
                                title: 'Delete Asset',
                                content: `Are you sure you want to delete "${record.name}"?`,
                                onOk: () => deleteAssetMutation.mutate(record.id),
                            })
                        }}
                    />
                </div>
            ),
        },
    ]

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files) {
            setUploadFiles(Array.from(files))
        }
    }

    const handleDiffForMerge = (sourceId: string, targetId: string) => {
        setMergeSourceBranch(sourceId)
        setMergeTargetBranch(targetId)
        diffMutation.mutate(
            { source_branch_id: sourceId, target_branch_id: targetId },
            {
                onSuccess: (data) => {
                    const items: MergeItem[] = []
                    data.episodes.forEach((ep) => {
                        if (ep.source_status && !ep.target_status) {
                            items.push({ item_type: 'episode', source_id: String(ep.number), action: 'adopt' })
                        }
                    })
                    data.assets.forEach((asset) => {
                        if (asset.in_source && !asset.in_target) {
                            items.push({ item_type: 'asset', source_id: asset.name, action: 'adopt' })
                        }
                    })
                    data.pits.forEach((pit) => {
                        if (pit.status_source && !pit.status_target) {
                            items.push({ item_type: 'pit', source_id: pit.title, action: 'adopt' })
                        }
                    })
                    setMergeItems(items)
                },
            },
        )
    }

    const renderDiffResult = (diff: DiffResponse) => (
        <div className="space-y-4 mt-4">
            {diff.episodes.length > 0 && (
                <div>
                    <Title heading={6}>Episodes</Title>
                    <Table
                        columns={[
                            { title: '#', dataIndex: 'number', key: 'number', width: 60 },
                            { title: 'Label', dataIndex: 'label', key: 'label', width: 80 },
                            {
                                title: 'Source Status',
                                dataIndex: 'source_status',
                                key: 'source_status',
                                width: 120,
                                render: (text: string | null) => text ? <Tag color={STATUS_COLORS[text] || ('default' as TagColor)}>{text}</Tag> : <Tag color="grey">N/A</Tag>,
                            },
                            {
                                title: 'Target Status',
                                dataIndex: 'target_status',
                                key: 'target_status',
                                width: 120,
                                render: (text: string | null) => text ? <Tag color={STATUS_COLORS[text] || ('default' as TagColor)}>{text}</Tag> : <Tag color="grey">N/A</Tag>,
                            },
                            { title: 'Source Title', dataIndex: 'title_source', key: 'title_source', render: (t: string | null) => t || '-' },
                            { title: 'Target Title', dataIndex: 'title_target', key: 'title_target', render: (t: string | null) => t || '-' },
                        ]}
                        dataSource={diff.episodes}
                        rowKey={(r?: { number: number }) => String(r?.number ?? '')}
                        pagination={false}
                        size="small"
                    />
                </div>
            )}
            {diff.assets.length > 0 && (
                <div>
                    <Title heading={6}>Assets</Title>
                    <Table
                        columns={[
                            { title: 'Name', dataIndex: 'name', key: 'name' },
                            {
                                title: 'Type',
                                dataIndex: 'asset_type',
                                key: 'asset_type',
                                width: 100,
                                render: (t: string) => <Tag color={ASSET_TYPE_COLORS[t] || ('default' as TagColor)}>{t}</Tag>,
                            },
                            {
                                title: 'In Source',
                                dataIndex: 'in_source',
                                key: 'in_source',
                                width: 90,
                                render: (v: boolean) => v ? <Tag color="green">Yes</Tag> : <Tag color="red">No</Tag>,
                            },
                            {
                                title: 'In Target',
                                dataIndex: 'in_target',
                                key: 'in_target',
                                width: 90,
                                render: (v: boolean) => v ? <Tag color="green">Yes</Tag> : <Tag color="red">No</Tag>,
                            },
                            { title: 'Source Desc', dataIndex: 'description_source', key: 'description_source', render: (t: string | null) => t || '-' },
                            { title: 'Target Desc', dataIndex: 'description_target', key: 'description_target', render: (t: string | null) => t || '-' },
                        ]}
                        dataSource={diff.assets}
                        rowKey={(r?: { name: string; asset_type: string }) => `${r?.name ?? ''}-${r?.asset_type ?? ''}`}
                        pagination={false}
                        size="small"
                    />
                </div>
            )}
            {diff.pits.length > 0 && (
                <div>
                    <Title heading={6}>Pits</Title>
                    <Table
                        columns={[
                            { title: 'Title', dataIndex: 'title', key: 'title' },
                            {
                                title: 'Source Status',
                                dataIndex: 'status_source',
                                key: 'status_source',
                                width: 120,
                                render: (t: string | null) => t ? <Tag color={PIT_STATUS_COLORS[t] || ('default' as TagColor)}>{t}</Tag> : <Tag color="grey">N/A</Tag>,
                            },
                            {
                                title: 'Target Status',
                                dataIndex: 'status_target',
                                key: 'status_target',
                                width: 120,
                                render: (t: string | null) => t ? <Tag color={PIT_STATUS_COLORS[t] || ('default' as TagColor)}>{t}</Tag> : <Tag color="grey">N/A</Tag>,
                            },
                        ]}
                        dataSource={diff.pits}
                        rowKey={(r?: { title: string }) => r?.title ?? ''}
                        pagination={false}
                        size="small"
                    />
                </div>
            )}
            {diff.canon_diff && (
                <div>
                    <Title heading={6}>Canon Rules Diff</Title>
                    <TextArea
                        value={JSON.stringify(diff.canon_diff, null, 2)}
                        rows={6}
                        readOnly
                    />
                </div>
            )}
            {diff.episodes.length === 0 && diff.assets.length === 0 && diff.pits.length === 0 && !diff.canon_diff && (
                <Empty description="No differences found" />
            )}
        </div>
    )

    return (
        <div>
            <div className="mb-6">
                <Title heading={3}>{project.title}</Title>
                <Paragraph>{project.description || 'No description'}</Paragraph>
                <div className="flex gap-2">
                    <Tag>{project.language.toUpperCase()}</Tag>
                    <Tag color="green">Main Branch</Tag>
                </div>
            </div>

            <Tabs>
                <TabPane tab="Episodes" itemKey="episodes">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-2 items-center">
                            <span>Branch:</span>
                            <select
                                className="border rounded px-2 py-1 text-sm"
                                value={selectedBranch || ''}
                                onChange={(e) => { setSelectedBranch(e.target.value || undefined); setEpisodePage(1) }}
                            >
                                <option value="">All</option>
                                {branches?.map((b) => (
                                    <option key={b.id} value={b.id}>{b.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="flex gap-2">
                            <Button icon={<IconLink />} onClick={() => navigate(`/projects/${projectId}/imports/mangadex`)}>
                                MangaDex 导入
                            </Button>
                            <Button icon={<IconForward />} onClick={() => setShowContinue(true)}>
                                Continue from Episode
                            </Button>
                            <Button icon={<IconPlus />} theme="solid" onClick={() => setShowImport(true)}>
                                Import Episode
                            </Button>
                        </div>
                    </div>

                    <Table
                        columns={episodeColumns}
                        dataSource={episodesData?.items || []}
                        loading={episodesLoading}
                        rowKey="id"
                        pagination={{
                            currentPage: episodePage,
                            pageSize: episodePageSize,
                            total: episodesData?.total || 0,
                            showTotal: true,
                            onChange: (currentPage: number, pageSize: number) => {
                                setEpisodePage(currentPage)
                                setEpisodePageSize(pageSize)
                            },
                        }}
                    />
                </TabPane>

                <TabPane tab="Assets" itemKey="assets">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-2 items-center">
                            <span>Type:</span>
                            <Select
                                value={assetTypeFilter}
                                onChange={(v: string | string[] | undefined) => { setAssetTypeFilter(v ? String(v) : undefined); setAssetPage(1) }}
                                style={{ width: 140 }}
                                placeholder="All Types"
                            >
                                <Select.Option value="">All</Select.Option>
                                {ASSET_TYPE_OPTIONS.map((opt) => (
                                    <Select.Option key={opt.value} value={opt.value}>{opt.label}</Select.Option>
                                ))}
                            </Select>
                        </div>
                        <div className="flex gap-2">
                            {selectedAssetIds.length >= 2 && (
                                <Button icon={<IconCopy />} onClick={() => setShowAssetMerge(true)}>
                                    Merge Selected ({selectedAssetIds.length})
                                </Button>
                            )}
                            <Button icon={<IconSearch />} loading={clusterMutation.isPending} onClick={() => clusterMutation.mutate()}>
                                Cluster Assets
                            </Button>
                            <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreateAsset(true)}>
                                Create Asset
                            </Button>
                        </div>
                    </div>
                    <Table
                        columns={[
                            {
                                title: '',
                                key: 'select',
                                width: 50,
                                render: (_: unknown, record: Asset) => (
                                    <Checkbox
                                        checked={selectedAssetIds.includes(record.id)}
                                        onChange={(e) => {
                                            if (Boolean(e.target.checked)) {
                                                setSelectedAssetIds([...selectedAssetIds, record.id])
                                            } else {
                                                setSelectedAssetIds(selectedAssetIds.filter((id) => id !== record.id))
                                            }
                                        }}
                                    />
                                ),
                            },
                            ...assetColumns,
                        ]}
                        dataSource={assetsData?.items || []}
                        loading={assetsLoading}
                        rowKey="id"
                        pagination={{
                            currentPage: assetPage,
                            pageSize: assetPageSize,
                            total: assetsData?.total || 0,
                            showTotal: true,
                            onChange: (currentPage: number, pageSize: number) => {
                                setAssetPage(currentPage)
                                setAssetPageSize(pageSize)
                            },
                        }}
                    />
                </TabPane>

                <TabPane tab="Pits" itemKey="pits">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-2 items-center">
                            <span>Status:</span>
                            <Select
                                value={pitStatusFilter}
                                onChange={(v: string | string[] | undefined) => { setPitStatusFilter(v ? String(v) : undefined); setPitPage(1) }}
                                style={{ width: 120 }}
                            >
                                <Select.Option value="">All</Select.Option>
                                <Select.Option value="open">Open</Select.Option>
                                <Select.Option value="resolved">Resolved</Select.Option>
                                <Select.Option value="abandoned">Abandoned</Select.Option>
                            </Select>
                        </div>
                        <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreatePit(true)}>
                            Create Pit
                        </Button>
                    </div>
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
                            onChange: (currentPage: number, pageSize: number) => {
                                setPitPage(currentPage)
                                setPitPageSize(pageSize)
                            },
                        }}
                    />
                </TabPane>

                <TabPane tab="Memory" itemKey="memory">
                    <div className="space-y-4">
                        <div>
                            <Title heading={5}>Canon Rules (Hard Settings)</Title>
                            <TextArea
                                value={JSON.stringify(canonRules, null, 2)}
                                onChange={(val: string) => {
                                    try { setCanonRules(JSON.parse(val)); setCanonValid(true) } catch { setCanonValid(false) }
                                }}
                                rows={8}
                                placeholder="Enter canon rules as JSON..."
                            />
                            <div className="mt-2 flex items-center gap-2">
                                <Button
                                    theme="solid"
                                    disabled={!canonValid}
                                    onClick={() => {
                                        memoryService.updateCanonRules(projectId!, canonRules).then(() => Toast.success('Canon rules updated')).catch(() => {})
                                    }}
                                >Save Canon Rules</Button>
                                {!canonValid && <Tag color="red">Invalid JSON</Tag>}
                            </div>
                        </div>
                        <div>
                            <Title heading={5}>Long Summary</Title>
                            <Paragraph>{project?.long_summary || 'No long summary yet. Understanding episodes will build this automatically.'}</Paragraph>
                        </div>
                        <div>
                            <Title heading={5}>RAG Search</Title>
                            <div className="flex gap-2">
                                <Input
                                    value={ragQuery}
                                    onChange={setRagQuery}
                                    placeholder="Search memories..."
                                    style={{ flex: 1 }}
                                />
                                <Button theme="solid" onClick={() => {
                                    memoryService.searchRag(projectId!, ragQuery).then((res) => setRagResults(res.results)).catch(() => {})
                                }}>Search</Button>
                            </div>
                            {ragResults.length > 0 && (
                                <div className="mt-2 space-y-2">
                                    {ragResults.map((r, i) => (
                                        <div key={i} className="border rounded p-2">
                                            <Tag size="small">Score: {r.score?.toFixed(3)}</Tag>
                                            <span className="ml-2 text-sm">{String(r.payload?.content || '')}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </TabPane>

                <TabPane tab="Branches" itemKey="branches">
                    <div className="flex justify-between items-center mb-4">
                        <div />
                        <div className="flex gap-2">
                            <Button icon={<IconCopy />} onClick={() => setShowFork(true)}>
                                Fork from Episode
                            </Button>
                            <Button icon={<IconSearch />} onClick={() => { setDiffResult(null); setShowDiff(true) }}>
                                Compare Branches
                            </Button>
                            <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreateBranch(true)}>
                                Create Branch
                            </Button>
                        </div>
                    </div>
                    <Table
                        columns={branchColumns}
                        dataSource={branches || []}
                        rowKey="id"
                        pagination={{ pageSize: 50, showTotal: true }}
                    />
                </TabPane>
            </Tabs>

            <Modal
                title="Import Episode"
                visible={showImport}
                onCancel={() => { setShowImport(false); setUploadFiles([]) }}
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
                            files: uploadFiles,
                        })
                    }}
                    initValues={{ branch_id: mainBranch?.id }}
                >
                    <Form.Select field="branch_id" label="Branch" style={{ width: '100%' }}>
                        {branches?.map((b) => (
                            <Select.Option key={b.id} value={b.id}>{b.name}</Select.Option>
                        ))}
                    </Form.Select>
                    <Form.InputNumber field="number" label="Sort Order" min={0.01} step={0.5} rules={[{ required: true }]} />
                    <Form.Input field="label" label="Episode Number (e.g. 36, 36.5, 番外1)" />
                    <Form.Select field="category" label="Category" style={{ width: '100%' }} initValue="regular">
                        <Select.Option value="regular">正篇</Select.Option>
                        <Select.Option value="special">番外</Select.Option>
                        <Select.Option value="extra">加笔</Select.Option>
                    </Form.Select>
                    <Form.Input field="title" label="Title (optional)" />
                    <div className="mb-4">
                        <label className="block text-sm font-medium mb-1">Images</label>
                        <input
                            type="file"
                            multiple
                            accept="image/*,.zip"
                            onChange={handleFileChange}
                            className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                        />
                        {uploadFiles.length > 0 && (
                            <div className="mt-2 text-sm text-gray-600">
                                {uploadFiles.length} file(s) selected
                            </div>
                        )}
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => { setShowImport(false); setUploadFiles([]) }}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={importMutation.isPending}>Import</Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="Continue from Episode"
                visible={showContinue}
                onCancel={() => setShowContinue(false)}
                footer={null}
                width={520}
            >
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Base Episode</label>
                        <Select
                            value={continueForm.base_episode_id}
                            onChange={(v: string | string[] | undefined) => setContinueForm({ ...continueForm, base_episode_id: String(v || '') })}
                            style={{ width: '100%' }}
                            placeholder="Select an episode"
                        >
                            {(episodesData?.items || []).map((e: Episode) => (
                                <Select.Option key={e.id} value={e.id}>
                                    {e.label} - {e.title || e.status}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Tone</label>
                        <Select
                            value={continueForm.tone}
                            onChange={(v: string | string[] | undefined) => setContinueForm({ ...continueForm, tone: String(v || 'main') })}
                            style={{ width: '100%' }}
                        >
                            <Select.Option value="main">Main Plot</Select.Option>
                            <Select.Option value="daily">Daily / Slice of Life</Select.Option>
                            <Select.Option value="climax">Climax</Select.Option>
                            <Select.Option value="filler">Filler</Select.Option>
                            <Select.Option value="pit_resolve">Resolve Foreshadowing</Select.Option>
                        </Select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Custom Instructions (optional)</label>
                        <TextArea
                            value={continueForm.custom_instructions}
                            onChange={(v: string) => setContinueForm({ ...continueForm, custom_instructions: v })}
                            placeholder="Any specific requirements for the next episode..."
                            rows={3}
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Title (optional)</label>
                        <Input
                            value={continueForm.title}
                            onChange={(v: string) => setContinueForm({ ...continueForm, title: v })}
                            placeholder="Episode title"
                        />
                    </div>
                    <div className="grid grid-cols-3 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1">Image Backend</label>
                            <Select
                                value={continueForm.image_backend}
                                onChange={(v: string | string[] | undefined) => setContinueForm({ ...continueForm, image_backend: v ? String(v) : undefined })}
                                style={{ width: '100%' }}
                                placeholder="Default"
                            >
                                <Select.Option value="openai">OpenAI</Select.Option>
                                <Select.Option value="custom">Custom HTTP</Select.Option>
                                <Select.Option value="mock">Mock</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1">Image Model</label>
                            <Select
                                value={continueForm.image_model}
                                onChange={(v: string | string[] | undefined) => setContinueForm({ ...continueForm, image_model: v ? String(v) : undefined })}
                                style={{ width: '100%' }}
                                placeholder="Default"
                            >
                                <Select.Option value="gpt-image-2">GPT-Image-2</Select.Option>
                                <Select.Option value="dall-e-3">DALL-E 3</Select.Option>
                            </Select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1">Image Size</label>
                            <Select
                                value={continueForm.image_size}
                                onChange={(v: string | string[] | undefined) => setContinueForm({ ...continueForm, image_size: v ? String(v) : undefined })}
                                style={{ width: '100%' }}
                                placeholder="Default"
                            >
                                <Select.Option value="1024x1024">1024x1024</Select.Option>
                                <Select.Option value="1024x1792">1024x1792</Select.Option>
                                <Select.Option value="1792x1024">1792x1024</Select.Option>
                            </Select>
                        </div>
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowContinue(false)}>Cancel</Button>
                        <Button
                            theme="solid"
                            loading={continueMutation.isPending}
                            disabled={!continueForm.base_episode_id}
                            onClick={() => continueMutation.mutate()}
                        >
                            Continue Generation
                        </Button>
                    </div>
                </div>
            </Modal>

            <Modal
                title="Create Pit"
                visible={showCreatePit}
                onCancel={() => setShowCreatePit(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createPitMutation.mutate({
                            title: String(values.title || ''),
                            description: values.description ? String(values.description) : undefined,
                            priority: values.priority ? Number(values.priority) : 0,
                            introduced_episode_id: String(values.introduced_episode_id || ''),
                            trigger_hint: values.trigger_hint ? String(values.trigger_hint) : undefined,
                        })
                    }}
                    initValues={{ priority: 0 }}
                >
                    <Form.Input field="title" label="Title" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="Description (optional)" />
                    <Form.InputNumber field="priority" label="Priority" min={0} max={10} />
                    <Form.Select field="introduced_episode_id" label="Introduced Episode" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {(episodesData?.items || []).map((e: Episode) => (
                            <Select.Option key={e.id} value={e.id}>
                                {e.label} - {e.title || e.status}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="trigger_hint" label="Trigger Hint (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowCreatePit(false)}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={createPitMutation.isPending}>Create</Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="Resolve Pit"
                visible={showResolvePit}
                onCancel={() => { setShowResolvePit(false); setResolvingPit(null) }}
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
                    >
                        <div className="mb-4">
                            <Tag color="blue">{resolvingPit.title}</Tag>
                            <span className="ml-2 text-sm text-gray-600">{resolvingPit.description}</span>
                        </div>
                        <Form.Select field="resolved_episode_id" label="Resolved Episode" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {(episodesData?.items || []).map((e: Episode) => (
                                <Select.Option key={e.id} value={e.id}>
                                    {e.label} - {e.title || e.status}
                                </Select.Option>
                            ))}
                        </Form.Select>
                        <div className="flex justify-end gap-2">
                            <Button onClick={() => { setShowResolvePit(false); setResolvingPit(null) }}>Cancel</Button>
                            <Button htmlType="submit" theme="solid" loading={resolvePitMutation.isPending}>Resolve</Button>
                        </div>
                    </Form>
                )}
            </Modal>

            <Modal
                title="Create Branch"
                visible={showCreateBranch}
                onCancel={() => setShowCreateBranch(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createBranchMutation.mutate({
                            name: String(values.name || ''),
                            description: values.description ? String(values.description) : undefined,
                        })
                    }}
                >
                    <Form.Input field="name" label="Branch Name" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="Description (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowCreateBranch(false)}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={createBranchMutation.isPending}>Create</Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="Fork from Episode"
                visible={showFork}
                onCancel={() => setShowFork(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        forkMutation.mutate({
                            episode_id: String(values.episode_id || ''),
                            branch_name: String(values.branch_name || ''),
                            description: values.description ? String(values.description) : undefined,
                        })
                    }}
                >
                    <Form.Select field="episode_id" label="Episode" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {(episodesData?.items || []).map((e: Episode) => (
                            <Select.Option key={e.id} value={e.id}>
                                {e.label} - {e.title || e.status}
                            </Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="branch_name" label="Branch Name" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="Description (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowFork(false)}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={forkMutation.isPending}>Fork</Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="Compare Branches (Diff)"
                visible={showDiff}
                onCancel={() => { setShowDiff(false); setDiffResult(null) }}
                footer={null}
                width={900}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        diffMutation.mutate({
                            source_branch_id: String(values.source_branch_id || ''),
                            target_branch_id: String(values.target_branch_id || ''),
                            episode_number: values.episode_number ? Number(values.episode_number) : undefined,
                        })
                    }}
                >
                    <div className="grid grid-cols-2 gap-4">
                        <Form.Select field="source_branch_id" label="Source Branch" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {branches?.map((b) => (
                                <Select.Option key={b.id} value={b.id}>{b.name}</Select.Option>
                            ))}
                        </Form.Select>
                        <Form.Select field="target_branch_id" label="Target Branch" style={{ width: '100%' }} rules={[{ required: true }]}>
                            {branches?.map((b) => (
                                <Select.Option key={b.id} value={b.id}>{b.name}</Select.Option>
                            ))}
                        </Form.Select>
                    </div>
                    <Form.InputNumber field="episode_number" label="Episode Number Filter (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => { setShowDiff(false); setDiffResult(null) }}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={diffMutation.isPending}>Compare</Button>
                    </div>
                </Form>
                {diffResult && renderDiffResult(diffResult)}
            </Modal>

            <Modal
                title="Merge Branches"
                visible={showMerge}
                onCancel={() => {
                    setShowMerge(false)
                    setDiffResult(null)
                    setMergeItems([])
                    setMergeSourceBranch('')
                    setMergeTargetBranch('')
                }}
                footer={null}
                width={900}
            >
                {!diffResult ? (
                    <Form
                        onSubmit={(values: Record<string, unknown>) => {
                            handleDiffForMerge(
                                String(values.source_branch_id || ''),
                                String(values.target_branch_id || ''),
                            )
                        }}
                    >
                        <div className="grid grid-cols-2 gap-4">
                            <Form.Select field="source_branch_id" label="Source Branch" style={{ width: '100%' }} rules={[{ required: true }]}>
                                {branches?.map((b) => (
                                    <Select.Option key={b.id} value={b.id}>{b.name}</Select.Option>
                                ))}
                            </Form.Select>
                            <Form.Select field="target_branch_id" label="Target Branch" style={{ width: '100%' }} rules={[{ required: true }]}>
                                {branches?.map((b) => (
                                    <Select.Option key={b.id} value={b.id}>{b.name}</Select.Option>
                                ))}
                            </Form.Select>
                        </div>
                        <div className="flex justify-end gap-2 mt-4">
                            <Button onClick={() => { setShowMerge(false); setMergeSourceBranch(''); setMergeTargetBranch('') }}>Cancel</Button>
                            <Button htmlType="submit" theme="solid" loading={diffMutation.isPending}>Load Diff</Button>
                        </div>
                    </Form>
                ) : (
                    <div>
                        {renderDiffResult(diffResult)}
                        <div className="mt-4 border-t pt-4">
                            <Title heading={6}>Merge Actions</Title>
                            {mergeItems.length === 0 ? (
                                <Empty description="No items to merge" />
                            ) : (
                                <Table
                                    columns={[
                                        { title: 'Type', dataIndex: 'item_type', key: 'item_type', width: 100, render: (t: string) => <Tag>{t}</Tag> },
                                        { title: 'Source ID', dataIndex: 'source_id', key: 'source_id' },
                                        {
                                            title: 'Action',
                                            dataIndex: 'action',
                                            key: 'action',
                                            width: 160,
                                            render: (action: string, _record: MergeItem, index: number) => (
                                                <RadioGroup
                                                    value={action}
                                                    options={[
                                                        { label: 'Adopt', value: 'adopt' },
                                                        { label: 'Skip', value: 'skip' },
                                                    ]}
                                                    onChange={(e) => {
                                                        const newItems = [...mergeItems]
                                                        newItems[index] = { ...newItems[index], action: String(e.target.value) as 'adopt' | 'skip' }
                                                        setMergeItems(newItems)
                                                    }}
                                                    type="button"
                                                />
                                            ),
                                        },
                                    ]}
                                    dataSource={mergeItems}
                                    rowKey={(r?: MergeItem) => `${r?.item_type ?? ''}-${r?.source_id ?? ''}`}
                                    pagination={false}
                                    size="small"
                                />
                            )}
                        </div>
                        <div className="flex justify-end gap-2 mt-4">
                            <Button onClick={() => {
                                setShowMerge(false)
                                setDiffResult(null)
                                setMergeItems([])
                                setMergeSourceBranch('')
                                setMergeTargetBranch('')
                            }}>Cancel</Button>
                            <Button
                                theme="solid"
                                loading={mergeMutation.isPending}
                                disabled={mergeItems.length === 0}
                                onClick={() => {
                                    mergeMutation.mutate({
                                        source_branch_id: mergeSourceBranch,
                                        target_branch_id: mergeTargetBranch,
                                        items: mergeItems,
                                    })
                                }}
                            >
                                Merge ({mergeItems.filter((i) => i.action === 'adopt').length} adopt, {mergeItems.filter((i) => i.action === 'skip').length} skip)
                            </Button>
                        </div>
                    </div>
                )}
            </Modal>

            <Modal
                title="Create Asset"
                visible={showCreateAsset}
                onCancel={() => setShowCreateAsset(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values: Record<string, unknown>) => {
                        createAssetMutation.mutate({
                            type: String(values.type || ''),
                            name: String(values.name || ''),
                            description: values.description ? String(values.description) : undefined,
                        })
                    }}
                    initValues={{ type: 'character' }}
                >
                    <Form.Select field="type" label="Type" style={{ width: '100%' }} rules={[{ required: true }]}>
                        {ASSET_TYPE_OPTIONS.map((opt) => (
                            <Select.Option key={opt.value} value={opt.value}>{opt.label}</Select.Option>
                        ))}
                    </Form.Select>
                    <Form.Input field="name" label="Name" rules={[{ required: true }]} />
                    <Form.TextArea field="description" label="Description (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowCreateAsset(false)}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={createAssetMutation.isPending}>Create</Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="Edit Asset"
                visible={!!editingAsset}
                onCancel={() => setEditingAsset(null)}
                footer={null}
            >
                {editingAsset && (
                    <Form
                        onSubmit={(values: Record<string, unknown>) => {
                            updateAssetMutation.mutate({
                                assetId: editingAsset.id,
                                updates: {
                                    name: String(values.name || ''),
                                    description: values.description ? String(values.description) : undefined,
                                },
                            })
                        }}
                        initValues={{ name: editingAsset.name, description: editingAsset.description || '' }}
                    >
                        <Form.Input field="name" label="Name" rules={[{ required: true }]} />
                        <Form.TextArea field="description" label="Description" />
                        <div className="flex justify-end gap-2">
                            <Button onClick={() => setEditingAsset(null)}>Cancel</Button>
                            <Button htmlType="submit" theme="solid" loading={updateAssetMutation.isPending}>Save</Button>
                        </div>
                    </Form>
                )}
            </Modal>

            <Modal
                title="Asset Clusters"
                visible={showClusterResult}
                onCancel={() => { setShowClusterResult(false); setClusterData(null) }}
                footer={null}
                width={800}
            >
                {clusterData && (
                    <div className="space-y-4">
                        <Descriptions
                            data={[
                                { key: 'Total Assets', value: String(clusterData.total_assets) },
                                { key: 'Clusters', value: String(clusterData.clusters.length) },
                                { key: 'Unclustered', value: String(clusterData.unclustered) },
                            ]}
                        />
                        {clusterData.clusters.length === 0 ? (
                            <Empty description="No clusters found" />
                        ) : (
                            clusterData.clusters.map((group, i) => (
                                <div key={i} className="border rounded p-3">
                                    <div className="flex items-center gap-2 mb-2">
                                        <Tag color={ASSET_TYPE_COLORS[group.asset_type] || ('default' as TagColor)}>{group.asset_type}</Tag>
                                        <span className="font-medium">{group.representative_name}</span>
                                        <Tag size="small">{group.items.length} items</Tag>
                                    </div>
                                    <Table
                                        columns={[
                                            { title: 'Name', dataIndex: 'name', key: 'name' },
                                            { title: 'Type', dataIndex: 'asset_type', key: 'asset_type', width: 100, render: (t: string) => <Tag color={ASSET_TYPE_COLORS[t] || ('default' as TagColor)}>{t}</Tag> },
                                            { title: 'Similarity', dataIndex: 'similarity', key: 'similarity', width: 100, render: (v: number) => `${(v * 100).toFixed(1)}%` },
                                        ]}
                                        dataSource={group.items}
                                        rowKey="asset_id"
                                        pagination={false}
                                        size="small"
                                    />
                                </div>
                            ))
                        )}
                    </div>
                )}
            </Modal>

            <Modal
                title="Similar Assets"
                visible={showSimilar}
                onCancel={() => { setShowSimilar(false); setSimilarAssets([]) }}
                footer={null}
            >
                {similarAssets.length === 0 ? (
                    <Empty description="No similar assets found" />
                ) : (
                    <Table
                        columns={[
                            { title: 'Name', dataIndex: 'name', key: 'name' },
                            { title: 'Type', dataIndex: 'asset_type', key: 'asset_type', width: 100, render: (t: string) => <Tag color={ASSET_TYPE_COLORS[t] || ('default' as TagColor)}>{t}</Tag> },
                            { title: 'Similarity', dataIndex: 'similarity', key: 'similarity', width: 100, render: (v: number) => `${(v * 100).toFixed(1)}%` },
                        ]}
                        dataSource={similarAssets}
                        rowKey="asset_id"
                        pagination={false}
                        size="small"
                    />
                )}
            </Modal>

            <Modal
                title="Merge Assets"
                visible={showAssetMerge}
                onCancel={() => { setShowAssetMerge(false); setSelectedAssetIds([]) }}
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
                    initValues={{
                        target_name: assetsData?.items?.find((a: Asset) => a.id === selectedAssetIds[0])?.name || '',
                    }}
                >
                    <div className="mb-4">
                        <span className="text-sm text-gray-600">Merging {selectedAssetIds.length} assets:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                            {selectedAssetIds.map((id) => {
                                const asset = assetsData?.items?.find((a: Asset) => a.id === id)
                                return asset ? <Tag key={id}>{asset.name}</Tag> : null
                            })}
                        </div>
                    </div>
                    <Form.Input field="target_name" label="Target Name" rules={[{ required: true }]} />
                    <Form.TextArea field="target_description" label="Target Description (optional)" />
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => { setShowAssetMerge(false); setSelectedAssetIds([]) }}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={assetMergeMutation.isPending}>Merge</Button>
                    </div>
                </Form>
            </Modal>
        </div>
    )
}
