import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
    Button,
    Empty,
    Spin,
    Modal,
    Form,
    Input,
    Select,
    Toast,
    Popconfirm,
    Pagination,
    Tag,
    TextArea,
} from '@douyinfe/semi-ui'
import { IconPlus, IconDelete, IconLink, IconSearch } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService, importService } from '@/services/project'
import type { CreateProjectRequest } from '@/services/project'

const LANG_LABELS: Record<string, string> = {
    zh: '中文连载 (ZH)',
    ja: '日漫原版 (JA)',
    en: '英文连载 (EN)',
}

export default function ProjectList() {
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const queryClient = useQueryClient()
    const [showCreate, setShowCreate] = useState(() => searchParams.get('create') === '1')
    const [showMangaDexCreate, setShowMangaDexCreate] = useState(false)
    const [mdUrl, setMdUrl] = useState('')
    const [mdCurl, setMdCurl] = useState('')
    const [keyword, setKeyword] = useState('')
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(18)

    useEffect(() => {
        if (searchParams.get('create') === '1') {
            const next = new URLSearchParams(searchParams)
            next.delete('create')
            setSearchParams(next, { replace: true })
        }
    }, [searchParams, setSearchParams])

    const { data, isLoading } = useQuery({
        queryKey: ['projects', keyword, page, pageSize],
        queryFn: () => projectService.list(keyword || undefined, { page, page_size: pageSize }),
    })

    const createMutation = useMutation({
        mutationFn: (payload: CreateProjectRequest) => projectService.create(payload),
        onSuccess: (created) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            setShowCreate(false)
            Toast.success('连载项目已创建')
            navigate(`/projects/${created.id}`)
        },
        onError: () => {},
    })

    const mdCreateMutation = useMutation({
        mutationFn: () =>
            importService.createProjectFromMangaDex({
                source_url: mdUrl.trim(),
                request_curl: mdCurl.trim() || undefined,
                languages: ['zh', 'en', 'ja'],
                fill_project_metadata: true,
            }),
        onSuccess: (res) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            setShowMangaDexCreate(false)
            setMdUrl('')
            setMdCurl('')
            Toast.success('已从 MangaDex 创建项目并发现章节')
            navigate(`/projects/${res.project.id}/imports/mangadex`)
        },
        onError: () => {},
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => projectService.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['projects'] })
            Toast.success('项目已删除')
        },
        onError: () => {},
    })

    return (
        <div className="space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 m-0">连载作品库</h1>
                    <p className="text-sm text-slate-500 mt-1 mb-0">
                        管理全部漫画连载工程、世界观主线档案与多分支续画任务
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <Input
                        prefix={<IconSearch />}
                        placeholder="搜索作品名称..."
                        value={keyword}
                        onChange={(v: string) => {
                            setKeyword(v)
                            setPage(1)
                        }}
                        style={{ width: 240 }}
                    />
                    <Button icon={<IconLink />} onClick={() => setShowMangaDexCreate(true)}>
                        从 MangaDex 一键建档
                    </Button>
                    <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreate(true)}>
                        新建漫画项目
                    </Button>
                </div>
            </div>

            {isLoading && (
                <div className="py-16 flex justify-center">
                    <Spin size="large" />
                </div>
            )}

            {!isLoading && (!data?.items || data.items.length === 0) && (
                <div className="studio-card py-16 px-6 text-center">
                    <Empty
                        title="暂无连载项目"
                        description="新建一部漫画作品，上传已有章节图片或 ZIP，系统即可自动识别人物场景、提炼主线伏笔并续画新章节。"
                    />
                    <div className="mt-4 flex justify-center gap-3">
                        <Button icon={<IconPlus />} theme="solid" onClick={() => setShowCreate(true)}>
                            新建连载项目
                        </Button>
                        <Button icon={<IconLink />} onClick={() => setShowMangaDexCreate(true)}>
                            从 MangaDex 导入整部连载
                        </Button>
                    </div>
                </div>
            )}

            {!isLoading && data?.items && data.items.length > 0 && (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {data.items.map((project) => {
                            const bible = project.canon_rules?.story_bible
                            const mainPlot = bible?.main_plot
                            const ruleCount = bible?.discovered_rules?.length || 0
                            return (
                                <div
                                    key={project.id}
                                    onClick={() => navigate(`/projects/${project.id}`)}
                                    className="studio-card studio-card-hover p-5 relative group cursor-pointer flex flex-col justify-between space-y-4"
                                >
                                    <div className="space-y-2.5">
                                        <div className="flex items-start justify-between gap-2 pr-8">
                                            <h3 className="text-base font-bold text-slate-900 m-0 line-clamp-1">
                                                {project.title}
                                            </h3>
                                        </div>

                                        <div className="flex flex-wrap gap-1.5">
                                            <Tag color="indigo" size="small">
                                                {LANG_LABELS[project.language] || project.language.toUpperCase()}
                                            </Tag>
                                            {bible?.last_updated_episode && (
                                                <Tag color="cyan" size="small">
                                                    已解析至第 {bible.last_updated_episode} 话
                                                </Tag>
                                            )}
                                            {ruleCount > 0 && (
                                                <Tag color="purple" size="small">
                                                    世界法则 {ruleCount} 条
                                                </Tag>
                                            )}
                                        </div>

                                        <p className="text-xs text-slate-500 line-clamp-2 m-0">
                                            {project.description || '暂无简介'}
                                        </p>

                                        {mainPlot?.core_conflict ? (
                                            <div className="rounded-lg bg-indigo-50/75 border border-indigo-100 p-3 text-xs space-y-1">
                                                <div className="font-semibold text-indigo-800">核心主线：</div>
                                                <div className="text-indigo-950 line-clamp-2">
                                                    {mainPlot.core_conflict}
                                                </div>
                                            </div>
                                        ) : project.long_summary ? (
                                            <div className="rounded-lg bg-slate-50 border border-slate-100 p-3 text-xs text-slate-600 line-clamp-2">
                                                {project.long_summary}
                                            </div>
                                        ) : (
                                            <div className="rounded-lg bg-slate-50 border border-dashed border-slate-200 p-3 text-xs text-slate-400">
                                                尚未运行多模态剧情理解，进入项目后可一键按序理解全书
                                            </div>
                                        )}
                                    </div>

                                    <div className="flex items-center justify-between pt-3 border-t border-slate-100 text-xs text-slate-400">
                                        <span>更新于 {new Date(project.updated_at).toLocaleDateString()}</span>
                                        <span className="font-medium text-indigo-600">打开工作台 →</span>
                                    </div>

                                    <div
                                        className="absolute top-3.5 right-3.5 opacity-0 group-hover:opacity-100 transition-opacity"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <Popconfirm
                                            title="确认删除该连载项目？"
                                            content="删除后该作品下的所有章节、资产与记忆将一并清理。"
                                            onConfirm={() => deleteMutation.mutate(project.id)}
                                        >
                                            <Button icon={<IconDelete />} type="danger" theme="light" size="small" />
                                        </Popconfirm>
                                    </div>
                                </div>
                            )
                        })}
                    </div>

                    {(data.total || 0) > pageSize && (
                        <div className="flex justify-center pt-4">
                            <Pagination
                                currentPage={page}
                                pageSize={pageSize}
                                total={data.total || 0}
                                showTotal
                                onChange={(currentPage: number, nextSize: number) => {
                                    setPage(currentPage)
                                    setPageSize(nextSize)
                                }}
                            />
                        </div>
                    )}
                </>
            )}

            <Modal
                title="新建连载漫画项目"
                visible={showCreate}
                onCancel={() => setShowCreate(false)}
                footer={null}
            >
                <Form
                    onSubmit={(values) => {
                        createMutation.mutate(values as CreateProjectRequest)
                    }}
                >
                    <Form.Input
                        field="title"
                        label="作品标题"
                        placeholder="例如：星之匣物语 / 葬送的芙莉莲"
                        rules={[{ required: true, message: '请输入作品标题' }]}
                    />
                    <Form.Select field="language" label="对白与剧本语言" initValue="zh" style={{ width: '100%' }}>
                        <Select.Option value="zh">简体中文 (国漫 / 汉化连载)</Select.Option>
                        <Select.Option value="ja">日本語 (日漫原版连载)</Select.Option>
                        <Select.Option value="en">English (美漫 / 英文版)</Select.Option>
                    </Form.Select>
                    <Form.TextArea
                        field="description"
                        label="世界观或作品简介（可选）"
                        placeholder="简要描述故事背景或题材风格，后续系统也会从漫画页面中自动提炼主线与设定..."
                        maxLength={800}
                        rows={4}
                    />
                    <div className="flex justify-end gap-2 mt-5">
                        <Button onClick={() => setShowCreate(false)}>取消</Button>
                        <Button htmlType="submit" theme="solid" loading={createMutation.isPending}>
                            创建并进入工作台
                        </Button>
                    </div>
                </Form>
            </Modal>

            <Modal
                title="从 MangaDex 一键创建连载工程"
                visible={showMangaDexCreate}
                onCancel={() => setShowMangaDexCreate(false)}
                footer={null}
                width={560}
            >
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">MangaDex 作品主页链接</label>
                        <Input
                            value={mdUrl}
                            onChange={setMdUrl}
                            placeholder="https://mangadex.org/title/..."
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">浏览器请求 cURL（可选，遇到 401 时粘贴）</label>
                        <TextArea
                            value={mdCurl}
                            onChange={setMdCurl}
                            rows={4}
                            placeholder="可选：粘贴任意 MangaDex 请求的 curl 以自动携带鉴权请求头"
                        />
                    </div>
                    <div className="flex justify-end gap-2 pt-2">
                        <Button onClick={() => setShowMangaDexCreate(false)}>取消</Button>
                        <Button
                            theme="solid"
                            loading={mdCreateMutation.isPending}
                            disabled={!mdUrl.trim()}
                            onClick={() => mdCreateMutation.mutate()}
                        >
                            解析作品并发现章节
                        </Button>
                    </div>
                </div>
            </Modal>
        </div>
    )
}
