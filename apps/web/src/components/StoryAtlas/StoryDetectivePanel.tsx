import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Input, Spin, Tag, Toast } from '@douyinfe/semi-ui'
import { IconSearch, IconBolt } from '@douyinfe/semi-icons'
import { memoryService, storageFileUrl } from '@/services/project'
import type { StoryBibleQAResponse, StoryGraphCharacterNode } from '@/services/project'

function renderInlineMarkdown(text: string): ReactNode[] {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    return parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
            return (
                <strong key={i} className="font-bold text-slate-900">
                    {part.slice(2, -2)}
                </strong>
            )
        }
        if (part.startsWith('`') && part.endsWith('`')) {
            return (
                <code key={i} className="px-1 py-0.5 rounded bg-slate-100 text-indigo-700 text-[12px] font-mono">
                    {part.slice(1, -1)}
                </code>
            )
        }
        return part
    })
}

function renderMarkdownAnswer(md: string): ReactNode {
    const lines = md.split('\n')
    const blocks: ReactNode[] = []
    lines.forEach((rawLine, idx) => {
        const line = rawLine.trim()
        if (!line) return
        if (line.startsWith('### ')) {
            blocks.push(
                <h5 key={idx} className="text-sm font-bold text-indigo-900 mt-3 mb-1">
                    {renderInlineMarkdown(line.slice(4))}
                </h5>,
            )
        } else if (line.startsWith('## ')) {
            blocks.push(
                <h4 key={idx} className="text-base font-extrabold text-slate-900 mt-3 mb-1.5 border-b border-slate-100 pb-1">
                    {renderInlineMarkdown(line.slice(3))}
                </h4>,
            )
        } else if (/^[-*]\s+/.test(line)) {
            blocks.push(
                <div key={idx} className="flex gap-2 pl-2 text-sm text-slate-700 leading-relaxed">
                    <span className="text-indigo-500 font-bold shrink-0">•</span>
                    <div>{renderInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</div>
                </div>,
            )
        } else if (/^\d+\.\s+/.test(line)) {
            const match = line.match(/^(\d+\.)\s+(.*)$/)
            blocks.push(
                <div key={idx} className="flex gap-2 pl-2 text-sm text-slate-700 leading-relaxed">
                    <span className="text-indigo-600 font-bold shrink-0">{match?.[1]}</span>
                    <div>{renderInlineMarkdown(match?.[2] || line)}</div>
                </div>,
            )
        } else {
            blocks.push(
                <p key={idx} className="text-sm text-slate-700 leading-relaxed m-0">
                    {renderInlineMarkdown(line)}
                </p>,
            )
        }
    })
    return <div className="space-y-1.5">{blocks}</div>
}

interface Props {
    projectId: string
    branchId: string
    characters: StoryGraphCharacterNode[]
}

export default function StoryDetectivePanel({ projectId, branchId, characters }: Props) {
    const navigate = useNavigate()
    const [question, setQuestion] = useState('')
    const [loading, setLoading] = useState(false)
    const [history, setHistory] = useState<StoryBibleQAResponse[]>([])

    const leadName = characters[0]?.name || '主角'
    const starterQuestions = [
        `总结目前为止主线剧情的关键转折与悬念是什么？`,
        `${leadName}在已连载章节中展现过哪些核心能力、口癖或关键道具？`,
        `目前还有哪些高优先级未回收伏笔，最适合在下一话回收？`,
    ]

    const submitQuestion = async (q: string) => {
        const trimmed = q.trim()
        if (!trimmed || loading) return
        setLoading(true)
        try {
            const res = await memoryService.askBible(projectId, {
                question: trimmed,
                branch_id: branchId || undefined,
            })
            setHistory((prev) => [res, ...prev])
            setQuestion('')
        } catch {
            Toast.error('查询 Story Bible 失败，请检查后端模型配置')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-base font-bold text-slate-900 m-0">剧情侦探 · Story Bible 问答引擎</h3>
                <p className="text-xs text-slate-500 m-0 mt-0.5">
                    结合层级篇章摘要、Multi-Query RRF 检索、角色档案与伏笔台账，严格基于已入库漫画内容作答并附带可跳转章节引证
                </p>
            </div>

            <div className="rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50/70 via-white to-slate-50 p-4 space-y-3">
                <div className="flex gap-2">
                    <Input
                        size="large"
                        prefix={<IconSearch />}
                        value={question}
                        onChange={setQuestion}
                        onEnterPress={() => submitQuestion(question)}
                        placeholder="向全书设定集提问，例如：某角色第几话出场？某条伏笔有哪些线索？"
                    />
                    <Button
                        theme="solid"
                        size="large"
                        icon={<IconBolt />}
                        loading={loading}
                        onClick={() => submitQuestion(question)}
                    >
                        提问查证
                    </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                    {starterQuestions.map((sq, idx) => (
                        <button
                            key={idx}
                            type="button"
                            onClick={() => submitQuestion(sq)}
                            className="text-xs bg-white hover:bg-indigo-50 text-indigo-800 border border-indigo-200/80 rounded-full px-3 py-1 transition cursor-pointer"
                        >
                            {sq}
                        </button>
                    ))}
                </div>
            </div>

            {loading && (
                <div className="rounded-2xl border border-slate-200 bg-white p-8 flex flex-col items-center gap-2">
                    <Spin size="large" />
                    <div className="text-xs text-slate-500">正在联合检索层级篇章记忆、人物档案与原始章节引证...</div>
                </div>
            )}

            {history.length > 0 && (
                <div className="space-y-4">
                    {history.map((item, idx) => (
                        <div key={idx} className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
                            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2.5">
                                <div className="font-bold text-sm text-slate-900">Q: {item.question}</div>
                                <Tag size="small" color="indigo">
                                    {item.model}
                                </Tag>
                            </div>

                            <div>{renderMarkdownAnswer(item.answer)}</div>

                            {item.matched_characters.length > 0 && (
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-xs font-semibold text-slate-500">涉及角色：</span>
                                    {item.matched_characters.map((mc) => (
                                        <span
                                            key={mc.id}
                                            className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 border border-slate-200 pl-1 pr-2.5 py-0.5 text-xs font-medium text-slate-800"
                                        >
                                            {mc.avatar_path ? (
                                                <img
                                                    src={storageFileUrl(mc.avatar_path)}
                                                    alt={mc.name}
                                                    className="w-5 h-5 rounded-full object-cover"
                                                />
                                            ) : (
                                                <span className="w-5 h-5 rounded-full bg-indigo-600 text-white text-[10px] flex items-center justify-center">
                                                    {mc.name.slice(0, 1)}
                                                </span>
                                            )}
                                            {mc.name}
                                        </span>
                                    ))}
                                </div>
                            )}

                            {item.citations.length > 0 && (
                                <div className="space-y-2">
                                    <div className="text-xs font-bold text-slate-500 uppercase">
                                        证据来源引证 ({item.citations.length})
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
                                        {item.citations.map((ci, cIdx) => (
                                            <div
                                                key={cIdx}
                                                onClick={() => navigate(`/projects/${projectId}/episodes/${ci.episode_id}`)}
                                                className="rounded-xl border border-slate-200 hover:border-indigo-400 bg-slate-50/70 p-2.5 flex gap-2.5 cursor-pointer transition"
                                            >
                                                {ci.page_image_path && (
                                                    <img
                                                        src={storageFileUrl(ci.page_image_path)}
                                                        alt={`Ep ${ci.episode_label}`}
                                                        className="w-12 h-16 rounded object-cover shrink-0 border border-slate-200"
                                                    />
                                                )}
                                                <div className="min-w-0 flex-1 space-y-1">
                                                    <div className="flex items-center gap-1.5">
                                                        <Tag size="small" color="blue">
                                                            第 {ci.episode_label} 话
                                                        </Tag>
                                                        <span className="text-[10px] text-slate-400 truncate">{ci.type}</span>
                                                    </div>
                                                    <div className="text-[11px] text-slate-700 line-clamp-3 leading-snug">
                                                        {ci.excerpt}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
