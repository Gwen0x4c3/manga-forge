import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Tabs, TabPane, Typography, Spin, Button, Table, Tag, Modal, Form, Select, Toast, Empty } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService, branchService, episodeService } from '@/services/project'
import type { Episode } from '@/services/project'

const { Title, Paragraph } = Typography

const STATUS_COLORS: Record<string, TagColor> = {
    imported: 'blue',
    understood: 'cyan',
    scripted: 'green',
    rendered: 'orange',
    published: 'purple',
}

interface ImportFormValues {
    branch_id: string
    number: number
    title?: string
}

export default function ProjectDetail() {
    const { id: projectId } = useParams<{ id: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [showImport, setShowImport] = useState(false)
    const [selectedBranch, setSelectedBranch] = useState<string | undefined>()
    const [uploadFiles, setUploadFiles] = useState<File[]>([])

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

    const mainBranch = branches?.find((b) => b.name === 'main')

    const importMutation = useMutation({
        mutationFn: async (data: { branch_id: string; number: number; title?: string; files: File[] }) => {
            const formData = new FormData()
            formData.append('branch_id', data.branch_id)
            formData.append('number', String(data.number))
            if (data.title) formData.append('title', data.title)
            data.files.forEach((f) => formData.append('files', f))
            return episodeService.importFiles(projectId!, formData)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowImport(false)
            setUploadFiles([])
            Toast.success('Episode imported')
        },
        onError: () => Toast.error('Failed to import episode'),
    })

    if (projectLoading) return <Spin size="large" />
    if (!project) return <Empty description="Project not found" />

    const episodeColumns = [
        { title: '#', dataIndex: 'number', key: 'number', width: 60 },
        { title: 'Title', dataIndex: 'title', key: 'title', render: (text: string) => text || '-' },
        { title: 'Source', dataIndex: 'source', key: 'source', render: (text: string) => <Tag>{text}</Tag> },
        {
            title: 'Status',
            dataIndex: 'status',
            key: 'status',
            render: (text: string) => <Tag color={STATUS_COLORS[text] || 'default'}>{text}</Tag>,
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
                <Button size="small" onClick={() => navigate(`/projects/${projectId}/episodes/${record.id}`)}>
                    View
                </Button>
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
                        <Button icon={<IconPlus />} theme="solid" onClick={() => setShowImport(true)}>
                            Import Episode
                        </Button>
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
                    <Empty description="Pit tracking coming in M3" />
                </TabPane>

                <TabPane tab="Memory" itemKey="memory">
                    <Empty description="Memory system coming in M1" />
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
                            title: formValues.title,
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
                    <Form.InputNumber field="number" label="Episode Number" min={1} rules={[{ required: true }]} />
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
        </div>
    )
}
