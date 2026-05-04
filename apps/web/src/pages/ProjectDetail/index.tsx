import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Tabs, TabPane, Typography, Spin, Button, Table, Tag, Modal, Form, Select, Toast, Empty, Input, TextArea } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus, IconForward, IconDelete } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService, branchService, episodeService, memoryService, generationService, pitService } from '@/services/project'
import type { Episode, Pit } from '@/services/project'

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
        queryKey: ['episodes', projectId, selectedBranch],
        queryFn: () => episodeService.list(projectId!, selectedBranch),
        enabled: !!projectId,
    })

    const { data: pitsData, isLoading: pitsLoading } = useQuery({
        queryKey: ['pits', projectId, pitStatusFilter],
        queryFn: () => pitService.list(projectId!, pitStatusFilter),
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

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files) {
            setUploadFiles(Array.from(files))
        }
    }

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
                                onChange={(e) => setSelectedBranch(e.target.value || undefined)}
                            >
                                <option value="">All</option>
                                {branches?.map((b) => (
                                    <option key={b.id} value={b.id}>{b.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="flex gap-2">
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
                        pagination={{ pageSize: 20 }}
                    />
                </TabPane>

                <TabPane tab="Assets" itemKey="assets">
                    <Empty description="Asset management coming in M4" />
                </TabPane>

                <TabPane tab="Pits" itemKey="pits">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-2 items-center">
                            <span>Status:</span>
                            <Select
                                value={pitStatusFilter}
                                onChange={(v: string | string[] | undefined) => setPitStatusFilter(v ? String(v) : undefined)}
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
                        pagination={{ pageSize: 20 }}
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
                    <Table
                        columns={[
                            { title: 'Name', dataIndex: 'name', key: 'name' },
                            { title: 'Created', dataIndex: 'created_at', key: 'created_at', render: (t: string) => new Date(t).toLocaleDateString() },
                        ]}
                        dataSource={branches || []}
                        rowKey="id"
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
        </div>
    )
}
