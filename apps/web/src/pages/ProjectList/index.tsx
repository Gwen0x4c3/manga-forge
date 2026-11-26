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
    TextArea,
} from '@douyinfe/semi-ui'
import { IconPlus, IconDelete, IconLink, IconSearch } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectService, importService, storageFileUrl } from '@/services/project'
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
    const [brokenCovers, setBrokenCovers] = useState<Record<string, boolean>>({})

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
            {/* Minimal Editorial Gallery Header */}
            <header className="pb-4 border-b flex flex-col md:flex-row md:items-end justify-between gap-4" style={{ borderColor: 'var(--border)' }}>
                <div>
                    <h1 className="font-editorial text-2xl font-bold m-0" style={{ color: 'var(--text-primary)' }}>
                        连载作品库
                    </h1>
                    <p className="text-xs mt-1 mb-0" style={{ color: 'var(--text-muted)' }}>
                        共 {data?.total ?? 0} 部漫画连载工程 · 点击封面进入编辑工作台
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Input
                        size="small"
                        prefix={<IconSearch />}
                        placeholder="检索作品名..."
                        value={keyword}
                        onChange={(v: string) => {
                            setKeyword(v)
                            setPage(1)
                        }}
                        style={{ width: 200 }}
                    />
                    <Button size="small" theme="light" icon={<IconLink />} onClick={() => setShowMangaDexCreate(true)}>
                        MangaDex 导入
                    </Button>
                    <Button size="small" icon={<IconPlus />} theme="solid" onClick={() => setShowCreate(true)}>
                        新建作品
                    </Button>
                </div>
            </header>

            {isLoading && (
                <div className="py-16 flex justify-center">
                    <Spin size="large" />
                </div>
            )}

            {!isLoading && (!data?.items || data.items.length === 0) && (
                <div className="py-20 text-center space-y-4 border rounded-md" style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-panel)' }}>
                    <Empty
                        title="尚无连载作品"
                        description="新建作品或从 MangaDex 导入连载章节，即可构建人物图谱、伏笔时间线并续画新章节。"
                    />
                    <div className="flex justify-center gap-2">
                        <Button size="small" icon={<IconPlus />} theme="solid" onClick={() => setShowCreate(true)}>
                            新建连载
                        </Button>
                        <Button size="small" theme="light" icon={<IconLink />} onClick={() => setShowMangaDexCreate(true)}>
                            从 MangaDex 导入
                        </Button>
                    </div>
                </div>
            )}

            {!isLoading && data?.items && data.items.length > 0 && (
                <>
                    {/* Editorial Print Book Gallery */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                        {data.items.map((project) => {
                            const bible = project.canon_rules?.story_bible
                            const mainPlot = bible?.main_plot
                            const epTotal = project.episode_count ?? 0
                            const epDone = project.understood_count ?? 0
                            const pct = epTotal > 0 ? Math.round((epDone / epTotal) * 100) : 0

                            return (
                                <article
                                    key={project.id}
                                    onClick={() => navigate(`/projects/${project.id}?view=episodes`)}
                                    className="group cursor-pointer flex flex-col relative"
                                >
                                    {/* Tankobon Cover Frame (2:3 Editorial Proportion) */}
                                    <div
                                        className="relative aspect-[3/4] rounded-[5px] border overflow-hidden transition-colors group-hover:border-[var(--accent)]"
                                        style={{
                                            backgroundColor: 'var(--bg-elevated)',
                                            borderColor: 'var(--border)',
                                        }}
                                    >
                                        {project.cover_image_path && !brokenCovers[project.id] ? (
                                            <img
                                                src={storageFileUrl(project.cover_image_path)}
                                                alt={project.title}
                                                onError={() =>
                                                    setBrokenCovers((prev) => ({ ...prev, [project.id]: true }))
                                                }
                                                className="w-full h-full object-cover object-top transition-transform duration-300 group-hover:scale-[1.02]"
                                            />
                                        ) : (
                                            <div className="w-full h-full px-5 pt-11 pb-5 flex flex-col justify-between bg-[var(--bg-panel)]">
                                                <div
                                                    className="font-mono text-[10px] uppercase tracking-widest"
                                                    style={{ color: 'var(--text-muted)' }}
                                                >
                                                    {LANG_LABELS[project.language] || project.language}
                                                </div>
                                                <div
                                                    className="font-editorial text-xl font-bold leading-snug line-clamp-3"
                                                    style={{ color: 'var(--text-primary)' }}
                                                >
                                                    {project.title}
                                                </div>
                                                <div
                                                    className="border-t pt-2 font-mono text-[10px] tracking-wider"
                                                    style={{
                                                        borderColor: 'var(--border)',
                                                        color: 'var(--text-muted)',
                                                    }}
                                                >
                                                    MANGAFORGE EDITION
                                                </div>
                                            </div>
                                        )}

                                        {/* Crisp top-left print stamp */}
                                        <span className="absolute top-2.5 left-2.5 font-mono text-[11px] font-semibold px-2 py-0.5 rounded-[3px] bg-[#18181B]/90 border border-[#38383D] text-[#F4F4F5] uppercase">
                                            {project.language} · {epTotal} 话
                                        </span>

                                        {/* Delete action on hover */}
                                        <div
                                            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            <Popconfirm
                                                title="确认删除该连载项目？"
                                                content="删除后该作品下的所有章节、资产与记忆将一并清理。"
                                                onConfirm={() => deleteMutation.mutate(project.id)}
                                            >
                                                <Button icon={<IconDelete />} type="danger" theme="solid" size="small" />
                                            </Popconfirm>
                                        </div>
                                    </div>

                                    {/* Editorial Typography Footer */}
                                    <div className="pt-3 space-y-2">
                                        <div className="flex items-start justify-between gap-2">
                                            <h3
                                                className="font-editorial text-base font-bold m-0 line-clamp-1 group-hover:text-[var(--accent)] transition-colors"
                                                style={{ color: 'var(--text-primary)' }}
                                            >
                                                {project.title}
                                            </h3>
                                        </div>

                                        <p className="text-[13px] m-0 line-clamp-2 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                            {mainPlot?.current_arc
                                                ? `当前篇章：${mainPlot.current_arc}`
                                                : project.description || '尚未导入或解析章节内容'}
                                        </p>

                                        {/* Minimal Linear Progress Bar + Timestamp */}
                                        <div className="pt-1 space-y-1.5">
                                            <div className="h-[2px] w-full overflow-hidden rounded" style={{ backgroundColor: 'var(--border)' }}>
                                                <div
                                                    className="h-full"
                                                    style={{ width: `${pct}%`, backgroundColor: 'var(--accent)' }}
                                                />
                                            </div>
                                            <div className="flex items-center justify-between text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                                                <span>已解析 {epDone}/{epTotal} 话</span>
                                                <span>{new Date(project.updated_at).toLocaleDateString()}</span>
                                            </div>
                                        </div>
                                    </div>
                                </article>
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
