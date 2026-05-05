import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
    Banner,
    Button,
    Checkbox,
    Empty,
    Input,
    Select,
    Spin,
    Table,
    TextArea,
    Tag,
    Toast,
    Typography,
} from '@douyinfe/semi-ui'
import { IconArrowLeft, IconImport, IconLink } from '@douyinfe/semi-icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchService, importService } from '@/services/project'
import type { Branch, ImportJob, ImportJobItem } from '@/services/project'

const { Title, Paragraph } = Typography

const IMPORT_STATUS_COLOR: Record<string, 'blue' | 'green' | 'red' | 'orange' | 'grey'> = {
    pending: 'grey',
    running: 'blue',
    imported: 'green',
    failed: 'red',
    selected: 'blue',
}

export default function MangaDexImportPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { projectId } = useParams<{ projectId: string }>()
    const [sourceUrl, setSourceUrl] = useState('')
    const [requestCurl, setRequestCurl] = useState('')
    const [branchId, setBranchId] = useState('')
    const [languages, setLanguages] = useState<string[]>(['zh', 'en', 'ja'])
    const [autoUnderstand, setAutoUnderstand] = useState(false)
    const [onlyMissing, setOnlyMissing] = useState(true)
    const [useDataSaver, setUseDataSaver] = useState(true)
    const [activeJob, setActiveJob] = useState<ImportJob | null>(null)
    const [selectedIds, setSelectedIds] = useState<string[]>([])

    const { data: branches } = useQuery({
        queryKey: ['branches', projectId],
        queryFn: () => branchService.list(projectId!),
        enabled: !!projectId,
    })

    const { data: jobsData, isLoading: jobsLoading } = useQuery({
        queryKey: ['import-jobs', projectId],
        queryFn: () => importService.listJobs(projectId!),
        enabled: !!projectId,
        refetchInterval: activeJob?.status === 'running' || activeJob?.status === 'queued' ? 3000 : false,
    })

    const { data: itemsData, isLoading: itemsLoading } = useQuery({
        queryKey: ['import-items', projectId, activeJob?.id],
        queryFn: () => importService.listItems(projectId!, activeJob!.id),
        enabled: !!projectId && !!activeJob?.id,
        refetchInterval: activeJob?.status === 'running' || activeJob?.status === 'queued' ? 3000 : false,
    })

    const defaultBranch = useMemo(
        () => branches?.find((branch: Branch) => branch.is_default) || branches?.[0],
        [branches],
    )

    const discoverMutation = useMutation({
        mutationFn: () =>
            importService.discoverForProject(projectId!, {
                source_url: sourceUrl,
                branch_id: branchId || defaultBranch?.id || '',
                request_curl: requestCurl.trim() || undefined,
                languages,
                fill_project_metadata: true,
                overwrite_project_metadata: false,
            }),
        onSuccess: (result) => {
            queryClient.invalidateQueries({ queryKey: ['project', projectId] })
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            queryClient.invalidateQueries({ queryKey: ['import-jobs', projectId] })
            setActiveJob(result.job)
            setSelectedIds(result.items.filter((item) => item.selection_status === 'selected').map((item) => item.id))
            Toast.success('章节发现完成')
        },
    })

    const updateSelectionMutation = useMutation({
        mutationFn: (data: { item_ids: string[]; action: 'select' | 'unselect' }) =>
            importService.updateSelection(projectId!, activeJob!.id, data),
        onSuccess: (result) => {
            setActiveJob(result.job)
            setSelectedIds(result.items.filter((item) => item.selection_status === 'selected').map((item) => item.id))
            queryClient.invalidateQueries({ queryKey: ['import-items', projectId, activeJob?.id] })
        },
    })

    const startMutation = useMutation({
        mutationFn: () =>
            importService.startJob(projectId!, activeJob!.id, {
                auto_understand: autoUnderstand,
                only_missing: onlyMissing,
                use_data_saver: useDataSaver,
                request_curl: requestCurl.trim() || undefined,
            }),
        onSuccess: (result) => {
            setActiveJob(result.job)
            queryClient.invalidateQueries({ queryKey: ['import-jobs', projectId] })
            Toast.success('导入任务已启动')
        },
    })

    const resumeMutation = useMutation({
        mutationFn: () =>
            importService.resumeJob(projectId!, activeJob!.id, {
                request_curl: requestCurl.trim() || undefined,
            }),
        onSuccess: (result) => {
            setActiveJob(result.job)
            queryClient.invalidateQueries({ queryKey: ['import-jobs', projectId] })
            Toast.success('已继续导入任务')
        },
    })

    const pauseMutation = useMutation({
        mutationFn: () => importService.pauseJob(projectId!, activeJob!.id),
        onSuccess: (job) => {
            setActiveJob(job)
            queryClient.invalidateQueries({ queryKey: ['import-jobs', projectId] })
            Toast.success('已暂停导入任务')
        },
    })

    const rows = itemsData || []

    useEffect(() => {
        if (!jobsData?.items || jobsData.items.length === 0) {
            return
        }
        if (!activeJob) {
            setActiveJob(jobsData.items[0])
            return
        }
        const refreshed = jobsData.items.find((job) => job.id === activeJob.id)
        if (refreshed) {
            setActiveJob(refreshed)
        }
    }, [jobsData, activeJob])

    useEffect(() => {
        if (!itemsData) {
            return
        }
        setSelectedIds(itemsData.filter((item) => item.selection_status === 'selected').map((item) => item.id))
    }, [itemsData])

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <Button icon={<IconArrowLeft />} theme="borderless" onClick={() => navigate(`/projects/${projectId}`)}>
                        返回项目
                    </Button>
                    <Title heading={3}>MangaDex 导入</Title>
                    <Paragraph>支持整部导入、缺失检测、单话勾选导入，以及任务暂停后继续。</Paragraph>
                </div>
                <Button icon={<IconLink />} onClick={() => navigate('/projects')}>
                    项目列表
                </Button>
            </div>

            <Banner
                type="info"
                description="语言优先级固定为中文、英文、日文优先；同章节存在多版本时会自动挑选优先语言版本。若接口 401，请粘贴 MangaDex 网站任意网络请求的 curl，系统会自动提取 Authorization。第一版恢复粒度为章节级。"
                closeIcon={null}
            />

            <div className="grid grid-cols-1 gap-4 rounded border p-4">
                <Input
                    value={sourceUrl}
                    onChange={setSourceUrl}
                    placeholder="粘贴 MangaDex 作品首页链接"
                    prefix="URL"
                />
                <TextArea
                    value={requestCurl}
                    onChange={setRequestCurl}
                    rows={6}
                    placeholder={`如果 MangaDex 接口 401，请在浏览器开发者工具里复制 MangaDex 任意请求的 curl，粘贴到这里。\n系统会自动解析 Authorization、Referer、User-Agent。`}
                />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <Select
                        value={branchId || defaultBranch?.id}
                        onChange={(value) => setBranchId(String(value || ''))}
                        placeholder="选择导入分支"
                    >
                        {branches?.map((branch: Branch) => (
                            <Select.Option key={branch.id} value={branch.id}>
                                {branch.name}
                            </Select.Option>
                        ))}
                    </Select>
                    <Select
                        multiple
                        value={languages}
                        onChange={(value) => setLanguages((value as string[]) || [])}
                        placeholder="语言优先级"
                    >
                        <Select.Option value="zh">中文</Select.Option>
                        <Select.Option value="en">英文</Select.Option>
                        <Select.Option value="ja">日文</Select.Option>
                    </Select>
                    <Button
                        theme="solid"
                        icon={<IconLink />}
                        loading={discoverMutation.isPending}
                        disabled={!sourceUrl.trim() || !(branchId || defaultBranch?.id)}
                        onClick={() => discoverMutation.mutate()}
                    >
                        发现章节
                    </Button>
                </div>
            </div>

            <div className="rounded border p-4 space-y-4">
                <div className="flex items-center justify-between">
                    <Title heading={5}>导入任务</Title>
                    {jobsLoading && <Spin size="small" />}
                </div>

                {!jobsLoading && (!jobsData?.items || jobsData.items.length === 0) && (
                    <Empty description="还没有导入任务，先输入 MangaDex 链接并发现章节。" />
                )}

                {!jobsLoading && jobsData?.items && jobsData.items.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {jobsData.items.map((job) => (
                            <Button
                                key={job.id}
                                theme={activeJob?.id === job.id ? 'solid' : 'light'}
                                onClick={() => {
                                    setActiveJob(job)
                                }}
                            >
                                {job.job_type} · {job.status}
                            </Button>
                        ))}
                    </div>
                )}

                {activeJob && (
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <Tag color={IMPORT_STATUS_COLOR[activeJob.status] || 'grey'}>{activeJob.status}</Tag>
                            <Tag>{activeJob.provider}</Tag>
                            {activeJob.external_series_id && <Tag>{activeJob.external_series_id}</Tag>}
                            <span className="text-sm text-gray-500">{activeJob.source_url}</span>
                        </div>

                        <div className="flex flex-wrap gap-4 text-sm text-gray-600">
                            <span>总数：{Number(activeJob.progress?.total || 0)}</span>
                            <span>待选：{Number(activeJob.progress?.selected || 0)}</span>
                            <span>已导入：{Number(activeJob.progress?.imported || 0)}</span>
                            <span>缺失：{Number(activeJob.progress?.missing || 0)}</span>
                            <span>失败：{Number(activeJob.progress?.failed || 0)}</span>
                        </div>

                        <div className="flex flex-wrap gap-4">
                            <Checkbox checked={autoUnderstand} onChange={(e) => setAutoUnderstand(Boolean(e.target.checked))}>
                                导入后自动理解
                            </Checkbox>
                            <Checkbox checked={onlyMissing} onChange={(e) => setOnlyMissing(Boolean(e.target.checked))}>
                                仅导入缺失章节
                            </Checkbox>
                            <Checkbox checked={useDataSaver} onChange={(e) => setUseDataSaver(Boolean(e.target.checked))}>
                                使用压缩图
                            </Checkbox>
                        </div>

                        <div className="flex flex-wrap gap-2">
                            <Button
                                icon={<IconImport />}
                                theme="solid"
                                loading={startMutation.isPending}
                                disabled={!activeJob.id || activeJob.status === 'running'}
                                onClick={() => startMutation.mutate()}
                            >
                                开始导入
                            </Button>
                            <Button
                                loading={resumeMutation.isPending}
                                disabled={!['paused', 'failed', 'partial_succeeded'].includes(activeJob.status)}
                                onClick={() => resumeMutation.mutate()}
                            >
                                继续导入
                            </Button>
                            <Button
                                disabled={activeJob.status !== 'running'}
                                loading={pauseMutation.isPending}
                                onClick={() => pauseMutation.mutate()}
                            >
                                暂停
                            </Button>
                            <Button
                                disabled={selectedIds.length === 0 || updateSelectionMutation.isPending}
                                onClick={() => updateSelectionMutation.mutate({ item_ids: selectedIds, action: 'unselect' })}
                            >
                                取消选中
                            </Button>
                            <Button
                                disabled={selectedIds.length === 0 || updateSelectionMutation.isPending}
                                onClick={() => updateSelectionMutation.mutate({ item_ids: selectedIds, action: 'select' })}
                            >
                                设为导入
                            </Button>
                        </div>
                    </div>
                )}
            </div>

            <div className="rounded border p-4">
                <div className="flex items-center justify-between mb-4">
                    <Title heading={5}>章节列表</Title>
                    {itemsLoading && <Spin size="small" />}
                </div>

                {!itemsLoading && rows.length === 0 && (
                    <Empty description="先发现章节，或切换到一个已有任务。" />
                )}

                {!itemsLoading && rows.length > 0 && (
                    <Table
                        rowKey="id"
                        pagination={{ pageSize: 50, showTotal: true }}
                        dataSource={rows}
                        columns={[
                            {
                                title: '',
                                key: 'select',
                                width: 48,
                                render: (_: unknown, record: ImportJobItem) => (
                                    <Checkbox
                                        checked={selectedIds.includes(record.id)}
                                        onChange={(e) => {
                                            if (e.target.checked) {
                                                setSelectedIds((prev) => [...prev, record.id])
                                            } else {
                                                setSelectedIds((prev) => prev.filter((itemId) => itemId !== record.id))
                                            }
                                        }}
                                    />
                                ),
                            },
                            { title: '章节', dataIndex: 'chapter_number', key: 'chapter_number', width: 100 },
                            { title: '标题', dataIndex: 'title', key: 'title', render: (text: string) => text || '-' },
                            { title: '卷', dataIndex: 'volume', key: 'volume', width: 80, render: (text: string) => text || '-' },
                            { title: '语言', dataIndex: 'translated_language', key: 'translated_language', width: 90 },
                            {
                                title: '汉化组',
                                dataIndex: 'group_names',
                                key: 'group_names',
                                render: (names: string[] | null) => names?.join(', ') || '-',
                            },
                            { title: '页数', dataIndex: 'page_count', key: 'page_count', width: 80, render: (value: number | null) => value ?? '-' },
                            {
                                title: '选择',
                                dataIndex: 'selection_status',
                                key: 'selection_status',
                                width: 100,
                                render: (text: string) => <Tag color={text === 'selected' ? 'blue' : 'grey'}>{text}</Tag>,
                            },
                            {
                                title: '状态',
                                dataIndex: 'import_status',
                                key: 'import_status',
                                width: 110,
                                render: (text: string) => <Tag color={IMPORT_STATUS_COLOR[text] || 'grey'}>{text}</Tag>,
                            },
                            {
                                title: '操作',
                                key: 'actions',
                                width: 140,
                                render: (_: unknown, record: ImportJobItem) => (
                                    <div className="flex gap-2">
                                        {record.episode_id ? (
                                            <Button size="small" onClick={() => navigate(`/projects/${projectId}/episodes/${record.episode_id}`)}>
                                                查看
                                            </Button>
                                        ) : (
                                            <Button
                                                size="small"
                                                onClick={() =>
                                                    updateSelectionMutation.mutate({
                                                        item_ids: [record.id],
                                                        action: record.selection_status === 'selected' ? 'unselect' : 'select',
                                                    })
                                                }
                                            >
                                                {record.selection_status === 'selected' ? '跳过' : '选中'}
                                            </Button>
                                        )}
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
            </div>
        </div>
    )
}
