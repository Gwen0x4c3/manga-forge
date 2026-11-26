import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Empty, Select, Tooltip } from '@douyinfe/semi-ui'
import type { StoryArcSummary, StoryBible, StoryPitSwimlane, StoryTimelineEpisode } from '@/services/project'
import ResizableInspector from '@/components/ResizableInspector'
import { IconExternal, IconZoomIn, IconZoomOut } from '@/components/StudioIcons'

interface Props {
    projectId: string
    episodes: StoryTimelineEpisode[]
    arcs: StoryArcSummary[]
    pits: StoryPitSwimlane[]
    storyBible: StoryBible
}

export default function PitSwimlaneTimeline({ projectId, episodes, arcs, pits }: Props) {
    const navigate = useNavigate()
    const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'resolved'>('all')
    const [priorityFilter, setPriorityFilter] = useState<'all' | 'high'>('all')
    const [groupByStatus, setGroupByStatus] = useState(true)
    const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
    const [zoom, setZoom] = useState<number>(1)
    const [selectedPitId, setSelectedPitId] = useState<string | null>(pits[0]?.id ?? null)

    const epByNum = useMemo(() => {
        const m = new Map<number, StoryTimelineEpisode>()
        episodes.forEach((e) => m.set(e.number, e))
        return m
    }, [episodes])

    const epIndexByNum = useMemo(() => {
        const m = new Map<number, number>()
        episodes.forEach((e, idx) => m.set(e.number, idx))
        return m
    }, [episodes])

    const filteredPits = useMemo(() => {
        return pits.filter((p) => {
            if (statusFilter !== 'all' && p.status !== statusFilter) return false
            if (priorityFilter === 'high' && p.priority < 8) return false
            return true
        })
    }, [pits, statusFilter, priorityFilter])

    const groups = useMemo(() => {
        if (!groupByStatus) {
            return [{ key: 'all', label: `全部伏笔 (${filteredPits.length})`, items: filteredPits }]
        }
        const open = filteredPits.filter((p) => p.status !== 'resolved')
        const resolved = filteredPits.filter((p) => p.status === 'resolved')
        const list = []
        if (open.length > 0) list.push({ key: 'open', label: `待回收伏笔 (${open.length})`, items: open })
        if (resolved.length > 0) list.push({ key: 'resolved', label: `已回收闭环 (${resolved.length})`, items: resolved })
        return list
    }, [filteredPits, groupByStatus])

    const selectedPit = pits.find((p) => p.id === selectedPitId) || filteredPits[0] || null

    const colWidth = Math.round(92 * zoom)
    const trackWidth = Math.max(episodes.length * colWidth, 420)
    const xForEpisodeNum = (epNo: number | null | undefined, fallbackIdx: number) => {
        if (episodes.length === 0) return colWidth / 2
        if (epNo !== null && epNo !== undefined) {
            const exact = epIndexByNum.get(epNo)
            if (exact !== undefined) return exact * colWidth + colWidth / 2
            // Interpolate nearest
            let bestIdx = fallbackIdx
            let bestDiff = Infinity
            episodes.forEach((e, i) => {
                const d = Math.abs(e.number - epNo)
                if (d < bestDiff) {
                    bestDiff = d
                    bestIdx = i
                }
            })
            return bestIdx * colWidth + colWidth / 2
        }
        return fallbackIdx * colWidth + colWidth / 2
    }

    const openCount = pits.filter((p) => p.status !== 'resolved').length
    const resolvedCount = pits.filter((p) => p.status === 'resolved').length

    return (
        <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* LEFT + CENTER GANTT WORKSPACE */}
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
                {/* Compact Timeline Toolbar */}
                <div
                    className="h-10 shrink-0 px-4 border-b flex items-center justify-between gap-3"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <div className="flex items-center gap-2">
                        <Select
                            size="small"
                            value={statusFilter}
                            onChange={(v) => setStatusFilter(v as 'all' | 'open' | 'resolved')}
                            style={{ width: 118 }}
                        >
                            <Select.Option value="all">全部状态</Select.Option>
                            <Select.Option value="open">待回收 ({openCount})</Select.Option>
                            <Select.Option value="resolved">已回收 ({resolvedCount})</Select.Option>
                        </Select>
                        <Select
                            size="small"
                            value={priorityFilter}
                            onChange={(v) => setPriorityFilter(v as 'all' | 'high')}
                            style={{ width: 126 }}
                        >
                            <Select.Option value="all">全部优先级</Select.Option>
                            <Select.Option value="high">仅高优 (P8+)</Select.Option>
                        </Select>
                        <button
                            type="button"
                            onClick={() => setGroupByStatus((v) => !v)}
                            className="h-6 px-2.5 rounded border text-[11px] cursor-pointer transition-colors"
                            style={{
                                backgroundColor: groupByStatus ? 'var(--bg-elevated)' : 'transparent',
                                borderColor: 'var(--border)',
                                color: groupByStatus ? 'var(--text-primary)' : 'var(--text-secondary)',
                            }}
                        >
                            按状态分组
                        </button>
                    </div>

                    {/* Semantic Legend + Zoom */}
                    <div className="flex items-center gap-4 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                        <div className="hidden lg:flex items-center gap-3.5">
                            <span className="inline-flex items-center gap-1.5">
                                <svg width="10" height="10" viewBox="0 0 10 10">
                                    <circle cx="5" cy="5" r="3.5" fill="#E64B35" />
                                </svg>
                                埋设
                            </span>
                            <span className="inline-flex items-center gap-1.5">
                                <svg width="10" height="10" viewBox="0 0 10 10">
                                    <polygon points="5,1 9,5 5,9 1,5" fill="var(--bg-panel)" stroke="var(--text-primary)" strokeWidth="1.4" />
                                </svg>
                                线索推进
                            </span>
                            <span className="inline-flex items-center gap-1.5">
                                <svg width="10" height="10" viewBox="0 0 10 10">
                                    <circle cx="5" cy="5" r="3.5" fill="none" stroke="var(--status-ok)" strokeWidth="1.5" />
                                    <circle cx="5" cy="5" r="1.4" fill="var(--status-ok)" />
                                </svg>
                                已回收
                            </span>
                        </div>

                        <div className="flex items-center gap-1 border-l pl-3" style={{ borderColor: 'var(--border)' }}>
                            <button
                                type="button"
                                onClick={() => setZoom((z) => Math.max(0.75, Number((z - 0.25).toFixed(2))))}
                                className="w-6 h-6 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                                style={{ color: 'var(--text-secondary)' }}
                            >
                                <IconZoomOut size={13} />
                            </button>
                            <span className="w-9 text-center font-mono text-[11px]" style={{ color: 'var(--text-primary)' }}>
                                {Math.round(zoom * 100)}%
                            </span>
                            <button
                                type="button"
                                onClick={() => setZoom((z) => Math.min(2, Number((z + 0.25).toFixed(2))))}
                                className="w-6 h-6 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                                style={{ color: 'var(--text-secondary)' }}
                            >
                                <IconZoomIn size={13} />
                            </button>
                        </div>
                    </div>
                </div>

                {/* Compact Arc Digest Strip */}
                {arcs.length > 0 && (
                    <div
                        className="px-4 py-2 border-b flex items-center gap-3 overflow-x-auto shrink-0 text-xs"
                        style={{ backgroundColor: 'var(--bg-app)', borderColor: 'var(--border-subtle)' }}
                    >
                        <span className="text-[10px] font-semibold uppercase tracking-wider shrink-0" style={{ color: 'var(--text-muted)' }}>
                            篇章区块
                        </span>
                        {arcs.map((arc, i) => (
                            <div
                                key={arc.key || i}
                                className="flex items-center gap-2 px-2.5 py-1 rounded border shrink-0 max-w-2xl"
                                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                            >
                                <span className="font-mono text-[11px] font-semibold shrink-0" style={{ color: 'var(--accent)' }}>
                                    Ep.{arc.start_episode}–{arc.end_episode}
                                </span>
                                <span className="truncate text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                    {arc.summary}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {/* STRICTLY ALIGNED GANTT MATRIX */}
                {filteredPits.length === 0 ? (
                    <div className="flex-1 flex items-center justify-center p-12">
                        <Empty description="当前筛选条件下暂无伏笔记录" />
                    </div>
                ) : (
                    <div className="flex-1 min-h-0 overflow-auto">
                        <div style={{ minWidth: 272 + trackWidth }}>
                            {/* Sticky Header Row: Frozen Pit Column + Episode Columns */}
                            <div
                                className="sticky top-0 z-20 flex border-b"
                                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                            >
                                <div
                                    className="w-[272px] shrink-0 sticky left-0 z-30 px-4 py-2.5 border-r text-[11px] font-semibold uppercase tracking-wider flex items-center justify-between"
                                    style={{
                                        backgroundColor: 'var(--bg-panel)',
                                        borderColor: 'var(--border)',
                                        color: 'var(--text-muted)',
                                    }}
                                >
                                    <span>伏笔轨道 ({filteredPits.length})</span>
                                    <span className="font-mono">PRIO</span>
                                </div>
                                <div className="flex" style={{ width: trackWidth }}>
                                    {episodes.map((ep) => (
                                        <button
                                            key={ep.id}
                                            type="button"
                                            onClick={() => navigate(`/projects/${projectId}/episodes/${ep.id}`)}
                                            style={{ width: colWidth, borderColor: 'var(--border-subtle)' }}
                                            className="shrink-0 px-2.5 py-2 border-r text-left bg-transparent hover:bg-[var(--bg-hover)] border-0 border-r cursor-pointer transition-colors"
                                        >
                                            <div className="flex items-center justify-between gap-1">
                                                <span className="font-mono text-[11px] font-semibold" style={{ color: 'var(--text-primary)' }}>
                                                    Ep.{ep.label}
                                                </span>
                                                {ep.source === 'generated' && (
                                                    <span
                                                        className="text-[9px] font-mono px-1 rounded-[2px] border"
                                                        style={{ color: 'var(--accent)', borderColor: 'var(--accent)' }}
                                                    >
                                                        续画
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-[10px] truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>
                                                {ep.title}
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Grouped Gantt Rows */}
                            {groups.map((grp) => {
                                const collapsed = Boolean(collapsedGroups[grp.key])
                                return (
                                    <div key={grp.key}>
                                        {groupByStatus && (
                                            <button
                                                type="button"
                                                onClick={() =>
                                                    setCollapsedGroups((prev) => ({ ...prev, [grp.key]: !prev[grp.key] }))
                                                }
                                                className="w-full flex items-center px-4 py-1.5 border-b text-left border-0 border-b cursor-pointer"
                                                style={{
                                                    backgroundColor: 'var(--bg-app)',
                                                    borderColor: 'var(--border-subtle)',
                                                    color: 'var(--text-secondary)',
                                                }}
                                            >
                                                <span className="font-mono text-[10px] mr-2">{collapsed ? '+' : '−'}</span>
                                                <span className="text-[11px] font-semibold">{grp.label}</span>
                                            </button>
                                        )}

                                        {!collapsed &&
                                            grp.items.map((pit) => {
                                                const isResolved = pit.status === 'resolved'
                                                const isSelected = selectedPit?.id === pit.id
                                                const startX = xForEpisodeNum(pit.introduced_episode_number, 0)
                                                const endX = xForEpisodeNum(
                                                    isResolved ? pit.resolved_episode_number : episodes[episodes.length - 1]?.number,
                                                    Math.max(0, episodes.length - 1),
                                                )
                                                const lineStroke = isResolved
                                                    ? 'var(--status-ok)'
                                                    : pit.priority >= 8
                                                      ? '#E64B35'
                                                      : '#A1A1AA'

                                                return (
                                                    <div
                                                        key={pit.id}
                                                        onClick={() => setSelectedPitId(pit.id)}
                                                        className="flex border-b cursor-pointer transition-colors"
                                                        style={{
                                                            borderColor: 'var(--border-subtle)',
                                                            backgroundColor: isSelected
                                                                ? 'var(--accent-subtle)'
                                                                : 'transparent',
                                                        }}
                                                    >
                                                        {/* Frozen Left Label Cell */}
                                                        <div
                                                            className="w-[272px] shrink-0 sticky left-0 z-10 px-4 py-2.5 border-r flex items-center justify-between gap-2"
                                                            style={{
                                                                backgroundColor: isSelected
                                                                    ? 'var(--bg-elevated)'
                                                                    : 'var(--bg-panel)',
                                                                borderColor: 'var(--border)',
                                                            }}
                                                        >
                                                            <div className="min-w-0 flex-1">
                                                                <div
                                                                    className="text-xs font-medium truncate"
                                                                    style={{
                                                                        color: isSelected
                                                                            ? 'var(--text-primary)'
                                                                            : 'var(--text-secondary)',
                                                                    }}
                                                                >
                                                                    {pit.title}
                                                                </div>
                                                                <div className="text-[10px] font-mono mt-0.5" style={{ color: 'var(--text-muted)' }}>
                                                                    Ep.{pit.introduced_episode_label || '?'}
                                                                    {isResolved
                                                                        ? ` → Ep.${pit.resolved_episode_label || '?'}`
                                                                        : ' → 进行中'}
                                                                </div>
                                                            </div>
                                                            <span
                                                                className="font-mono text-[10px] px-1.5 py-0.5 rounded-[3px] border shrink-0"
                                                                style={{
                                                                    borderColor:
                                                                        !isResolved && pit.priority >= 8
                                                                            ? 'var(--accent)'
                                                                            : 'var(--border)',
                                                                    color:
                                                                        !isResolved && pit.priority >= 8
                                                                            ? 'var(--accent)'
                                                                            : 'var(--text-muted)',
                                                                }}
                                                            >
                                                                P{pit.priority}
                                                            </span>
                                                        </div>

                                                        {/* Aligned SVG Track */}
                                                        <div className="relative h-12 shrink-0" style={{ width: trackWidth }}>
                                                            {/* Vertical chapter gridlines */}
                                                            {episodes.map((ep, i) => (
                                                                <div
                                                                    key={ep.id}
                                                                    className="absolute top-0 bottom-0 border-r pointer-events-none"
                                                                    style={{
                                                                        left: i * colWidth,
                                                                        width: colWidth,
                                                                        borderColor: 'var(--border-subtle)',
                                                                    }}
                                                                />
                                                            ))}

                                                            <svg
                                                                width={trackWidth}
                                                                height={48}
                                                                className="block relative z-10"
                                                            >
                                                                {/* Horizontal lifecycle track */}
                                                                {endX > startX && (
                                                                    <line
                                                                        x1={startX}
                                                                        y1={24}
                                                                        x2={endX}
                                                                        y2={24}
                                                                        stroke={lineStroke}
                                                                        strokeWidth={isSelected ? 2.4 : 1.8}
                                                                        strokeDasharray={isResolved ? undefined : '4 3'}
                                                                    />
                                                                )}

                                                                {/* Planted Node (Solid Circle) */}
                                                                <circle
                                                                    cx={startX}
                                                                    cy={24}
                                                                    r={4.5}
                                                                    fill={lineStroke}
                                                                    stroke="var(--bg-app)"
                                                                    strokeWidth={1.5}
                                                                />

                                                                {/* Clue Progression Nodes (Hollow Diamonds) */}
                                                                {pit.clues.map((cl, ci) => {
                                                                    const cx = xForEpisodeNum(cl.episode_number, 0)
                                                                    return (
                                                                        <Tooltip
                                                                            key={ci}
                                                                            content={`Ep.${cl.episode_number ?? '?'} 线索：${cl.text}`}
                                                                        >
                                                                            <polygon
                                                                                points={`${cx},18 ${cx + 5},24 ${cx},30 ${cx - 5},24`}
                                                                                fill="var(--bg-panel)"
                                                                                stroke="var(--text-primary)"
                                                                                strokeWidth={1.5}
                                                                            />
                                                                        </Tooltip>
                                                                    )
                                                                })}

                                                                {/* Resolved Stop Marker (Double Ring) */}
                                                                {isResolved && endX >= startX && (
                                                                    <g>
                                                                        <circle
                                                                            cx={endX}
                                                                            cy={24}
                                                                            r={6}
                                                                            fill="var(--bg-app)"
                                                                            stroke="var(--status-ok)"
                                                                            strokeWidth={1.6}
                                                                        />
                                                                        <circle cx={endX} cy={24} r={2.4} fill="var(--status-ok)" />
                                                                    </g>
                                                                )}
                                                            </svg>
                                                        </div>
                                                    </div>
                                                )
                                            })}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>

            {/* RIGHT INSPECTOR: Pit Brief & Manuscript Source Traceability */}
            <ResizableInspector
                title="伏笔档案"
                subtitle={selectedPit ? `P${selectedPit.priority}` : undefined}
            >
                {selectedPit ? (
                    <div className="space-y-4">
                        <div className="pb-3 border-b space-y-2" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div className="flex items-center justify-between gap-2 text-[11px] font-mono">
                                <span
                                    className="px-1.5 py-0.5 rounded-[3px] border"
                                    style={{
                                        borderColor:
                                            selectedPit.status === 'resolved' ? 'var(--status-ok)' : 'var(--accent)',
                                        color:
                                            selectedPit.status === 'resolved' ? 'var(--status-ok)' : 'var(--accent)',
                                    }}
                                >
                                    {selectedPit.status === 'resolved' ? '已回收闭环' : '待回收'}
                                </span>
                                <span style={{ color: 'var(--text-muted)' }}>优先级 P{selectedPit.priority}</span>
                            </div>
                            <h3 className="font-editorial text-sm font-bold m-0 leading-snug" style={{ color: 'var(--text-primary)' }}>
                                {selectedPit.title}
                            </h3>
                        </div>

                        <div className="space-y-1.5 pb-3 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                伏笔详情
                            </div>
                            <p className="text-xs leading-relaxed m-0" style={{ color: 'var(--text-secondary)' }}>
                                {selectedPit.description}
                            </p>
                        </div>

                        {selectedPit.trigger_hint && (
                            <div className="space-y-1 pb-3 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                                <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                    触发回收条件
                                </div>
                                <div className="text-xs leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                                    {selectedPit.trigger_hint}
                                </div>
                            </div>
                        )}

                        {/* Manuscript Source Links */}
                        <div className="space-y-2 pb-3 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                原稿溯源
                            </div>
                            <div className="space-y-1.5">
                                {selectedPit.introduced_episode_number !== null &&
                                    epByNum.get(selectedPit.introduced_episode_number) && (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                navigate(
                                                    `/projects/${projectId}/episodes/${
                                                        epByNum.get(selectedPit.introduced_episode_number!)!.id
                                                    }`,
                                                )
                                            }
                                            className="w-full px-2.5 py-2 rounded border text-left flex items-center justify-between gap-2 cursor-pointer transition-colors hover:bg-[var(--bg-hover)]"
                                            style={{
                                                backgroundColor: 'var(--bg-app)',
                                                borderColor: 'var(--border-subtle)',
                                                color: 'var(--text-primary)',
                                            }}
                                        >
                                            <span className="text-xs truncate">
                                                埋设于第 {selectedPit.introduced_episode_label} 话
                                            </span>
                                            <IconExternal size={12} />
                                        </button>
                                    )}
                                {selectedPit.resolved_episode_number !== null &&
                                    epByNum.get(selectedPit.resolved_episode_number) && (
                                        <button
                                            type="button"
                                            onClick={() =>
                                                navigate(
                                                    `/projects/${projectId}/episodes/${
                                                        epByNum.get(selectedPit.resolved_episode_number!)!.id
                                                    }`,
                                                )
                                            }
                                            className="w-full px-2.5 py-2 rounded border text-left flex items-center justify-between gap-2 cursor-pointer transition-colors hover:bg-[var(--bg-hover)]"
                                            style={{
                                                backgroundColor: 'var(--bg-app)',
                                                borderColor: 'var(--border-subtle)',
                                                color: 'var(--status-ok)',
                                            }}
                                        >
                                            <span className="text-xs truncate">
                                                回收于第 {selectedPit.resolved_episode_label} 话
                                            </span>
                                            <IconExternal size={12} />
                                        </button>
                                    )}
                            </div>
                        </div>

                        {/* Clue Progression List */}
                        <div className="space-y-2">
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                线索推进节点 ({selectedPit.clues.length})
                            </div>
                            {selectedPit.clues.length === 0 ? (
                                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    尚未记录中途线索推进
                                </div>
                            ) : (
                                <div className="space-y-2 border-l pl-3 ml-1" style={{ borderColor: 'var(--border)' }}>
                                    {selectedPit.clues.map((c, idx) => (
                                        <div key={idx} className="text-xs space-y-0.5">
                                            <div className="font-mono text-[11px]" style={{ color: 'var(--accent)' }}>
                                                {c.episode_number ? `Ep.${c.episode_number}` : '线索'}
                                            </div>
                                            <div className="leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                                {c.text}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <Empty description="选择左侧伏笔轨道查看详情与原稿溯源" />
                )}
            </ResizableInspector>
        </div>
    )
}
