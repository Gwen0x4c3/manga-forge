import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Empty, Input, Spin, Toast } from '@douyinfe/semi-ui'
import { memoryService, storageFileUrl } from '@/services/project'
import type { StoryBibleQAResponse, StoryGraphCharacterNode } from '@/services/project'
import ResizableInspector from '@/components/ResizableInspector'
import { IconResearch, IconExternal } from '@/components/StudioIcons'

interface Props {
    projectId: string
    branchId: string
    characters: StoryGraphCharacterNode[]
}

function renderInlineMarkdown(text: string): ReactNode[] {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    return parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
            return (
                <strong key={i} className="font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {part.slice(2, -2)}
                </strong>
            )
        }
        if (part.startsWith('`') && part.endsWith('`')) {
            return (
                <code
                    key={i}
                    className="px-1 py-0.5 rounded-[3px] font-mono text-[12px]"
                    style={{ backgroundColor: 'var(--bg-elevated)', color: 'var(--accent)' }}
                >
                    {part.slice(1, -1)}
                </code>
            )
        }
        return part
    })
}

function renderResearchMarkdown(md: string): ReactNode {
    const lines = md.split('\n')
    const blocks: ReactNode[] = []
    lines.forEach((rawLine, idx) => {
        const line = rawLine.trim()
        if (!line) return
        if (line.startsWith('### ')) {
            blocks.push(
                <h5
                    key={idx}
                    className="text-xs font-semibold uppercase tracking-wider mt-4 mb-1.5"
                    style={{ color: 'var(--accent)' }}
                >
                    {renderInlineMarkdown(line.slice(4))}
                </h5>,
            )
        } else if (line.startsWith('## ') || line.startsWith('# ')) {
            const titleText = line.startsWith('## ') ? line.slice(3) : line.slice(2)
            blocks.push(
                <h4
                    key={idx}
                    className="font-editorial text-base font-bold mt-4 mb-2 pb-1.5 border-b"
                    style={{ color: 'var(--text-primary)', borderColor: 'var(--border-subtle)' }}
                >
                    {renderInlineMarkdown(titleText)}
                </h4>,
            )
        } else if (/^[-*]\s+/.test(line)) {
            blocks.push(
                <div key={idx} className="flex gap-2.5 pl-1 text-[13px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    <span className="shrink-0 font-mono" style={{ color: 'var(--accent)' }}>
                        —
                    </span>
                    <div>{renderInlineMarkdown(line.replace(/^[-*]\s+/, ''))}</div>
                </div>,
            )
        } else if (/^\d+\.\s+/.test(line)) {
            const match = line.match(/^(\d+\.)\s+(.*)$/)
            blocks.push(
                <div key={idx} className="flex gap-2.5 pl-1 text-[13px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    <span className="shrink-0 font-mono font-semibold" style={{ color: 'var(--text-primary)' }}>
                        {match?.[1]}
                    </span>
                    <div>{renderInlineMarkdown(match?.[2] || line)}</div>
                </div>,
            )
        } else {
            blocks.push(
                <p key={idx} className="text-[13px] leading-relaxed m-0" style={{ color: 'var(--text-secondary)' }}>
                    {renderInlineMarkdown(line)}
                </p>,
            )
        }
    })
    return <div className="space-y-2">{blocks}</div>
}

export default function StoryDetectivePanel({ projectId, branchId, characters }: Props) {
    const navigate = useNavigate()
    const [question, setQuestion] = useState('')
    const [loading, setLoading] = useState(false)
    const [history, setHistory] = useState<StoryBibleQAResponse[]>([])
    const [activeIdx, setActiveIdx] = useState<number>(0)

    const leadName = characters[0]?.name || '主角'
    const presetQueries = [
        '总结目前为止主线剧情的关键转折与悬念',
        `${leadName}在已连载章节中展现过的核心能力、口癖与关键道具`,
        '梳理当前高优先级未回收伏笔及下话回收切入点',
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
            setActiveIdx(0)
            setQuestion('')
        } catch {
            Toast.error('查询 Story Bible 失败，请检查后端服务状态')
        } finally {
            setLoading(false)
        }
    }

    const activeReport = history[activeIdx] || null

    return (
        <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* COLUMN 1: Research Query History & Presets */}
            <aside
                className="w-60 shrink-0 border-r flex flex-col min-h-0"
                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
            >
                <div
                    className="h-10 px-3.5 border-b flex items-center justify-between shrink-0"
                    style={{ borderColor: 'var(--border)' }}
                >
                    <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                        研究记录 ({history.length})
                    </span>
                </div>

                <div className="flex-1 overflow-y-auto p-2.5 space-y-4">
                    {history.length > 0 && (
                        <div className="space-y-1">
                            {history.map((item, idx) => {
                                const active = idx === activeIdx
                                return (
                                    <button
                                        key={idx}
                                        type="button"
                                        onClick={() => setActiveIdx(idx)}
                                        className="w-full text-left px-2.5 py-2 rounded border-0 cursor-pointer transition-colors relative"
                                        style={{
                                            backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                                            color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                        }}
                                    >
                                        {active && (
                                            <span
                                                className="absolute left-0 top-1.5 bottom-1.5 w-[2px]"
                                                style={{ backgroundColor: 'var(--accent)' }}
                                            />
                                        )}
                                        <div className="text-xs line-clamp-2 leading-snug">{item.question}</div>
                                        <div className="text-[10px] font-mono mt-1" style={{ color: 'var(--text-muted)' }}>
                                            {item.citations.length} 条原稿引证 · {item.matched_characters.length} 角色
                                        </div>
                                    </button>
                                )
                            })}
                        </div>
                    )}

                    <div className="space-y-1.5 pt-2 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                        <div className="px-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            常用考据议题
                        </div>
                        {presetQueries.map((pq, i) => (
                            <button
                                key={i}
                                type="button"
                                disabled={loading}
                                onClick={() => submitQuestion(pq)}
                                className="w-full text-left px-2.5 py-2 rounded border text-xs leading-snug cursor-pointer transition-colors hover:bg-[var(--bg-hover)]"
                                style={{
                                    backgroundColor: 'var(--bg-app)',
                                    borderColor: 'var(--border-subtle)',
                                    color: 'var(--text-secondary)',
                                }}
                            >
                                {pq}
                            </button>
                        ))}
                    </div>
                </div>
            </aside>

            {/* COLUMN 2: Center Research Brief Workspace */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden" style={{ backgroundColor: 'var(--bg-app)' }}>
                {/* Top Research Query Bar */}
                <div
                    className="px-5 py-3 border-b flex items-center gap-2.5 shrink-0"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <Input
                        value={question}
                        onChange={setQuestion}
                        onEnterPress={() => submitQuestion(question)}
                        placeholder="输入考据或叙事检索问题（基于已入库章节记忆与原稿证据回答）..."
                        style={{ flex: 1 }}
                    />
                    <Button theme="solid" loading={loading} onClick={() => submitQuestion(question)}>
                        检索分析
                    </Button>
                </div>

                {/* Research Document Canvas */}
                <div className="flex-1 min-h-0 overflow-y-auto px-8 py-6">
                    <div className="max-w-3xl mx-auto">
                        {loading ? (
                            <div className="py-20 flex flex-col items-center gap-3">
                                <Spin size="large" />
                                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    正在联合检索篇章摘要、角色状态轨迹、伏笔台账与章节原稿引证...
                                </div>
                            </div>
                        ) : activeReport ? (
                            <article className="space-y-5">
                                <header className="pb-4 border-b space-y-2.5" style={{ borderColor: 'var(--border)' }}>
                                    <div className="flex items-center gap-2 text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                        <IconResearch size={13} />
                                        <span>STORY RESEARCH BRIEF</span>
                                        <span>·</span>
                                        <span>{activeReport.citations.length} 条原稿证据</span>
                                    </div>
                                    <h2 className="font-editorial text-xl font-bold m-0 leading-snug" style={{ color: 'var(--text-primary)' }}>
                                        {activeReport.question}
                                    </h2>

                                    {activeReport.matched_characters.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-2 pt-1">
                                            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                                关联角色：
                                            </span>
                                            {activeReport.matched_characters.map((mc) => (
                                                <span
                                                    key={mc.id}
                                                    className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[11px]"
                                                    style={{
                                                        backgroundColor: 'var(--bg-panel)',
                                                        borderColor: 'var(--border)',
                                                        color: 'var(--text-primary)',
                                                    }}
                                                >
                                                    {mc.avatar_path && (
                                                        <img
                                                            src={storageFileUrl(mc.avatar_path)}
                                                            alt={mc.name}
                                                            className="w-4 h-4 rounded-[2px] object-cover grayscale"
                                                        />
                                                    )}
                                                    {mc.name}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </header>

                                <div>{renderResearchMarkdown(activeReport.answer)}</div>
                            </article>
                        ) : (
                            <div className="py-20 space-y-4">
                                <div className="text-center space-y-1.5">
                                    <div className="font-editorial text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
                                        剧情研究与设定考据工作区
                                    </div>
                                    <p className="text-xs max-w-md mx-auto m-0" style={{ color: 'var(--text-muted)' }}>
                                        在上方输入问题或点击左侧预设议题。系统将严格依据已收录章节、角色档案与伏笔台账输出分析结论，并在右侧列出可溯源的原稿证据链。
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* COLUMN 3: Collapsible Resizable Manuscript Evidence Chain */}
            <ResizableInspector
                title="原稿证据链"
                subtitle={activeReport ? `${activeReport.citations.length} 处引证` : undefined}
            >
                {!activeReport || activeReport.citations.length === 0 ? (
                    <Empty description="执行检索分析后，此处将展示对应的章节原稿缩略图、对白摘录与溯源跳转链接。" />
                ) : (
                    <div className="space-y-3">
                        {activeReport.citations.map((ci, idx) => (
                            <div
                                key={idx}
                                className="rounded border p-2.5 space-y-2 transition-colors hover:border-[var(--accent)]"
                                style={{
                                    backgroundColor: 'var(--bg-app)',
                                    borderColor: 'var(--border-subtle)',
                                }}
                            >
                                <div className="flex items-start gap-2.5">
                                    {ci.page_image_path && (
                                        <div
                                            className="w-12 h-16 rounded-[3px] border overflow-hidden shrink-0"
                                            style={{ backgroundColor: 'var(--paper)', borderColor: 'var(--border)' }}
                                        >
                                            <img
                                                src={storageFileUrl(ci.page_image_path)}
                                                alt={`Ep ${ci.episode_label}`}
                                                className="w-full h-full object-cover"
                                            />
                                        </div>
                                    )}
                                    <div className="min-w-0 flex-1 space-y-1">
                                        <div className="flex items-center justify-between gap-1 text-[11px] font-mono">
                                            <span className="font-semibold" style={{ color: 'var(--accent)' }}>
                                                Ep.{ci.episode_label}
                                            </span>
                                            <span style={{ color: 'var(--text-muted)' }}>{ci.type}</span>
                                        </div>
                                        {ci.title && (
                                            <div className="text-xs font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                                                {ci.title}
                                            </div>
                                        )}
                                        <p
                                            className="text-[11px] leading-relaxed m-0 line-clamp-4"
                                            style={{ color: 'var(--text-secondary)' }}
                                        >
                                            {ci.excerpt}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex justify-end pt-1 border-t" style={{ borderColor: 'var(--border-subtle)' }}>
                                    <button
                                        type="button"
                                        onClick={() => navigate(`/projects/${projectId}/episodes/${ci.episode_id}`)}
                                        className="text-[11px] bg-transparent border-0 cursor-pointer flex items-center gap-1 hover:underline"
                                        style={{ color: 'var(--text-primary)' }}
                                    >
                                        <span>定位原稿</span>
                                        <IconExternal size={11} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </ResizableInspector>
        </div>
    )
}
