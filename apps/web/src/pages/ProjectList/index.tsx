import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Empty, Typography, Spin, Modal, Form, Input, Select, Toast, Popconfirm } from '@douyinfe/semi-ui'
import { IconPlus, IconDelete } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService } from '@/services/project'
import type { CreateProjectRequest } from '@/services/project'

const { Title, Paragraph } = Typography

export default function ProjectList() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [showCreate, setShowCreate] = useState(false)
    const [keyword, setKeyword] = useState('')

    const { data, isLoading } = useQuery({
        queryKey: ['projects', keyword],
        queryFn: () => projectService.list(keyword || undefined),
    })

    const createMutation = useMutation({
        mutationFn: (data: CreateProjectRequest) => projectService.create(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            setShowCreate(false)
            Toast.success('Project created')
        },
        onError: () => Toast.error('Failed to create project'),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => projectService.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            Toast.success('Project deleted')
        },
        onError: () => Toast.error('Failed to delete project'),
    })

    return (
        <div>
            <div className="flex justify-between items-center mb-6">
                <Title heading={3}>Projects</Title>
                <div className="flex gap-3">
                    <Input
                        placeholder="Search projects..."
                        value={keyword}
                        onChange={setKeyword}
                        style={{ width: 240 }}
                    />
                    <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreate(true)}>
                        New Project
                    </Button>
                </div>
            </div>

            {isLoading && <Spin size="large" />}

            {!isLoading && (!data?.items || data.items.length === 0) && (
                <Empty description="No projects yet. Create one to get started!" />
            )}

            {!isLoading && data?.items && data.items.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {data.items.map((project) => (
                        <div
                            key={project.id}
                            className="relative group cursor-pointer"
                            onClick={() => navigate(`/projects/${project.id}`)}
                        >
                            <Card className="hover:shadow-lg transition-shadow">
                                <Title heading={5}>{project.title}</Title>
                                <Paragraph ellipsis={{ rows: 2 }}>{project.description || 'No description'}</Paragraph>
                                <div className="flex justify-between items-center mt-2">
                                    <span className="text-xs text-gray-500">
                                        {project.language.toUpperCase()}
                                    </span>
                                    <span className="text-xs text-gray-500">
                                        {new Date(project.updated_at).toLocaleDateString()}
                                    </span>
                                </div>
                            </Card>
                            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                <Popconfirm
                                    title="Delete this project?"
                                    onConfirm={(e) => {
                                        e?.stopPropagation()
                                        deleteMutation.mutate(project.id)
                                    }}
                                >
                                    <Button
                                        icon={<IconDelete />}
                                        type="danger"
                                        size="small"
                                        onClick={(e) => e.stopPropagation()}
                                    />
                                </Popconfirm>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <Modal
                title="Create Project"
                visible={showCreate}
                onCancel={() => setShowCreate(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values) => {
                        createMutation.mutate(values as CreateProjectRequest)
                    }}
                >
                    <Form.Input field="title" label="Title" rules={[{ required: true, message: 'Title is required' }]} />
                    <Form.TextArea field="description" label="Description" maxLength={500} />
                    <Form.Select field="language" label="Language" initValue="zh" style={{ width: '100%' }}>
                        <Select.Option value="zh">Chinese</Select.Option>
                        <Select.Option value="ja">Japanese</Select.Option>
                        <Select.Option value="en">English</Select.Option>
                    </Form.Select>
                    <div className="flex justify-end gap-2 mt-4">
                        <Button onClick={() => setShowCreate(false)}>Cancel</Button>
                        <Button htmlType="submit" theme="solid" loading={createMutation.isPending}>Create</Button>
                    </div>
                </Form>
            </Modal>
        </div>
    )
}
