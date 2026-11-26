import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tag, Empty, Tooltip } from '@douyinfe/semi-ui'
import { storageFileUrl } from '@/services/project'
import type { StoryArcSummary, StoryBible, StoryPitSwimlane, StoryTimelineEpisode } from '@/services/project'

interface Props {
    projectId: string
    episodes: StoryTimelineEpisode[]
    arcs: StoryArcSummary[]
    pits: StoryPitSwimlane[]
    storyBible: StoryBible
}

export default function PitSwimlaneTimeline({ projectId, episodes, arcs, pits, storyBible }: Props) {
    const navigate = useNavigate()
    const [selectedPitId, setSelectedPitId] = useState<string | null>(pits[0]?.id ?? null)

    const epNumbers = episodes.map((e) => e.number)
    const minEp = epNumbers.length > 0 ? Math.min(...epNumbers) : 1
    const maxEp = epNumbers.length > 0 ? Math.max(...epNumbers) : 1
    const span = Math.max(1, maxEp - minEp)

    const pctForEpisode = (epNo: number) => {
        if (episodes.length <= 1) return 50
        return 6 + ((epNo - minEp) / span) * 88
    }

    const coreRules = storyBible.core_rules || []
    const discoveredRules = storyBible.discovered_rules || []
    const selectedPit = pits.find((p) => p.id === selectedPitId) || null

    return (
        <div className="space-y-6">
            {/* 1. Tiered World Rules + Arc Summaries */}
            {(arcs.length > 0 || coreRules.length > 0) && (
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                    <div className="lg:col-span-7 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/70 via-white to-violet-50/40 p-4 space-y-3">
                        <div className="flex items-center justify-between">
                            <h4 className="text-sm font-bold text-indigo-950 m-0">层级篇章压缩档案 (Arc Memory)</h4>
                            <Tag size="small" color="indigo">
                                {arcs.length} 个篇章块
                            </Tag>
                        </div>
                        {arcs.length === 0 ? (
                            <div className="text-xs text-slate-500">随着章节累积，每 10 话自动封存一个篇章级压缩摘要。</div>
                        ) : (
                            <div className="space-y-2.5">
                                {arcs.map((arc, idx) => (
                                    <div key={arc.key || idx} className="rounded-xl bg-white border border-indigo-100 p-3 space-y-1">
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="text-xs font-bold text-indigo-800">
                                                第 {arc.start_episode} – {arc.end_episode} 话
                                            </span>
                                            <Tag size="small" color={arc.sealed ? 'green' : 'blue'}>
                                                {arc.sealed ? '已封存篇章' : '活跃连载中'}
                                            </Tag>
                                        </div>
                                        <p className="text-xs text-slate-700 leading-relaxed m-0">{arc.summary}</p>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="lg:col-span-5 rounded-2xl border border-slate-200 bg-white p-4 space-y-3">
                        <div className="flex items-center justify-between">
                            <h4 className="text-sm font-bold text-slate-900 m-0">分层世界观法则</h4>
                            <span className="text-[11px] text-slate-500">
                                奠基 {coreRules.length} · 滚动 {discoveredRules.length}
                            </span>
                        </div>
                        {coreRules.length > 0 && (
                            <div className="space-y-1.5">
                                <div className="text-[11px] font-bold text-amber-700 uppercase">永不遗忘奠基法则 (Core Rules)</div>
                                <div className="space-y-1 max-h-32 overflow-y-auto">
                                    {coreRules.slice(0, 8).map((r, i) => (
                                        <div key={i} className="text-xs bg-amber-50/70 border border-amber-200/70 rounded-lg px-2.5 py-1.5 text-amber-950">
                                            ★ {r}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                        {discoveredRules.length > 0 && (
                            <div className="space-y-1.5">
                                <div className="text-[11px] font-bold text-slate-500 uppercase">近期演进法则 (Discovered)</div>
                                <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                                    {discoveredRules.slice(0, 10).map((r, i) => (
                                        <span key={i} className="text-[11px] bg-slate-50 border border-slate-200 rounded-md px-2 py-1 text-slate-700">
                                            {r}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* 2. Episode Timeline Strip */}
            <div className="space-y-2.5">
                <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-slate-900 m-0">连载时间轴 ({episodes.length} 话)</h4>
                    <span className="text-xs text-slate-500">点击章节卡片直达阅读与剧情解析</span>
                </div>
                {episodes.length === 0 ? (
                    <Empty description="当前分支暂无章节" />
                ) : (
                    <div
                        className={
                            episodes.length <= 6
                                ? 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3'
                                : 'flex gap-3 overflow-x-auto pb-2'
                        }
                    >
                        {episodes.map((ep) => (
                            <div
                                key={ep.id}
                                onClick={() => navigate(`/projects/${projectId}/episodes/${ep.id}`)}
                                className={`${
                                    episodes.length <= 6 ? 'w-full' : 'w-52 shrink-0'
                                } rounded-xl border border-slate-200 bg-white hover:border-indigo-400 hover:shadow-md transition cursor-pointer overflow-hidden flex flex-col`}
                            >
                                <div className="h-28 bg-slate-100 relative overflow-hidden">
                                    {ep.cover_path ? (
                                        <img
                                            src={storageFileUrl(ep.cover_path)}
                                            alt={ep.title}
                                            className="w-full h-full object-cover object-top"
                                        />
                                    ) : (
                                        <div className="w-full h-full flex items-center justify-center text-xs text-slate-400">
                                            暂无封面
                                        </div>
                                    )}
                                    <div className="absolute top-1.5 left-1.5 flex gap-1">
                                        <span className="px-1.5 py-0.5 rounded bg-slate-900/85 text-white text-[10px] font-bold shadow-sm">
                                            第 {ep.label} 话
                                        </span>
                                        {ep.source === 'generated' && (
                                            <span className="px-1.5 py-0.5 rounded bg-violet-600/95 text-white text-[10px] font-bold shadow-sm">
                                                AI 续画
                                            </span>
                                        )}
                                    </div>
                                </div>
                                <div className="p-2.5 space-y-1 flex-1 flex flex-col">
                                    <div className="text-xs font-bold text-slate-900 truncate">{ep.title}</div>
                                    <p className="text-[11px] text-slate-600 line-clamp-3 leading-relaxed m-0 flex-1">
                                        {ep.summary || '尚未执行剧情理解'}
                                    </p>
                                    {ep.cliffhanger && (
                                        <div className="text-[10px] text-amber-900 bg-amber-50 border border-amber-200/70 rounded px-1.5 py-0.5 truncate">
                                            悬念：{ep.cliffhanger}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* 3. Foreshadowing Pit Swimlanes */}
            <div className="rounded-2xl border border-slate-200 bg-white p-4 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                        <h4 className="text-sm font-bold text-slate-900 m-0">伏笔生命周期泳道 (Foreshadowing Swimlanes)</h4>
                        <p className="text-xs text-slate-500 m-0 mt-0.5">
                            追踪每条伏笔从埋下 (●) → 跨话线索推进 (◆) → 回收闭环 (✓) 的完整时间跨度
                        </p>
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-slate-600">
                        <span className="inline-flex items-center gap-1">
                            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" /> 高优待填
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block" /> 常规待填
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" /> 已回收
                        </span>
                        <span className="inline-flex items-center gap-1">
                            <span className="w-2.5 h-2.5 rotate-45 bg-indigo-600 inline-block" /> 线索推进
                        </span>
                    </div>
                </div>

                {pits.length === 0 ? (
                    <Empty description="暂无伏笔记录" />
                ) : (
                    <div className="space-y-3">
                        {/* Episode axis header */}
                        {episodes.length > 0 && (
                            <div className="grid grid-cols-12 items-center text-[11px] text-slate-500 px-3">
                                <div className="col-span-4 font-semibold text-slate-700">伏笔名称 / 优先级</div>
                                <div className="col-span-8 relative h-5">
                                    {episodes.map((ep) => (
                                        <span
                                            key={ep.id}
                                            className="absolute -translate-x-1/2 font-semibold"
                                            style={{ left: `${pctForEpisode(ep.number)}%` }}
                                        >
                                            Ep.{ep.label}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="space-y-2">
                            {pits.slice(0, 10).map((pit) => {
                                const isResolved = pit.status === 'resolved'
                                const startNo = pit.introduced_episode_number ?? minEp
                                const endNo = pit.resolved_episode_number ?? maxEp
                                const leftPct = pctForEpisode(startNo)
                                const rightPct = Math.max(leftPct, pctForEpisode(endNo))
                                const isSelected = selectedPitId === pit.id
                                const barColor = isResolved
                                    ? 'bg-emerald-500'
                                    : pit.priority >= 8
                                      ? 'bg-rose-500'
                                      : 'bg-amber-500'
                                const endBg = isResolved
                                    ? 'bg-emerald-600'
                                    : pit.priority >= 8
                                      ? 'bg-rose-600'
                                      : 'bg-amber-600'

                                return (
                                    <div
                                        key={pit.id}
                                        onClick={() => setSelectedPitId(pit.id)}
                                        className={`grid grid-cols-12 items-center rounded-xl px-3 py-2 cursor-pointer transition border ${
                                            isSelected
                                                ? 'border-indigo-400 bg-indigo-50/40'
                                                : 'border-slate-100 bg-slate-50/60 hover:border-slate-300'
                                        }`}
                                    >
                                        <div className="col-span-4 pr-3 min-w-0">
                                            <div className="flex items-center gap-1.5">
                                                <Tag size="small" color={isResolved ? 'green' : pit.priority >= 8 ? 'red' : 'orange'}>
                                                    P{pit.priority}
                                                </Tag>
                                                <span className="text-xs font-bold text-slate-800 truncate">{pit.title}</span>
                                            </div>
                                        </div>
                                        <div className="col-span-8 relative h-7 flex items-center">
                                            {/* Vertical episode guide ticks */}
                                            {episodes.map((ep) => (
                                                <span
                                                    key={ep.id}
                                                    className="absolute top-0 bottom-0 w-px bg-slate-200/70"
                                                    style={{ left: `${pctForEpisode(ep.number)}%` }}
                                                />
                                            ))}
                                            {/* Track baseline */}
                                            <div className="w-full h-0.5 bg-slate-200 rounded" />
                                            {/* Active span bar */}
                                            {rightPct > leftPct && (
                                                <div
                                                    className={`absolute h-2 rounded-full ${barColor} opacity-80`}
                                                    style={{
                                                        left: `${leftPct}%`,
                                                        width: `${Math.max(1, rightPct - leftPct)}%`,
                                                    }}
                                                />
                                            )}
                                            {/* Start dot */}
                                            <Tooltip content={`埋下于第 ${pit.introduced_episode_label || startNo} 话`}>
                                                <span
                                                    className={`absolute w-3.5 h-3.5 rounded-full border-2 border-white shadow ${barColor} -translate-x-1/2`}
                                                    style={{ left: `${leftPct}%` }}
                                                />
                                            </Tooltip>
                                            {/* Clue progression diamonds */}
                                            {pit.clues.map((cl, ci) => {
                                                const clPct = cl.episode_number
                                                    ? pctForEpisode(cl.episode_number)
                                                    : leftPct + (rightPct - leftPct) * ((ci + 1) / (pit.clues.length + 1))
                                                return (
                                                    <Tooltip
                                                        key={ci}
                                                        content={`第 ${cl.episode_number ?? '?'} 话线索：${cl.text}`}
                                                    >
                                                        <span
                                                            className="absolute w-3 h-3 rotate-45 bg-indigo-600 border border-white shadow -translate-x-1/2"
                                                            style={{ left: `${clPct}%` }}
                                                        />
                                                    </Tooltip>
                                                )
                                            })}
                                            {/* Clean circular end status badge */}
                                            {rightPct > leftPct + 1 && (
                                                <span
                                                    className={`absolute -translate-x-1/2 w-4 h-4 rounded-full ${endBg} text-white text-[9px] font-bold flex items-center justify-center shadow`}
                                                    style={{ left: `${rightPct}%` }}
                                                >
                                                    {isResolved ? '✓' : '→'}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>

                        {/* Selected Pit Inspector Card */}
                        {selectedPit && (
                            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3.5 space-y-2 text-xs">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="font-bold text-slate-900 text-sm">{selectedPit.title}</span>
                                    <div className="flex gap-1.5">
                                        <Tag size="small" color={selectedPit.status === 'resolved' ? 'green' : 'amber'}>
                                            {selectedPit.status === 'resolved' ? '已回收' : '待填伏笔'}
                                        </Tag>
                                        {selectedPit.introduced_episode_label && (
                                            <Tag size="small" color="blue">
                                                埋设：第 {selectedPit.introduced_episode_label} 话
                                            </Tag>
                                        )}
                                        {selectedPit.resolved_episode_label && (
                                            <Tag size="small" color="green">
                                                回收：第 {selectedPit.resolved_episode_label} 话
                                            </Tag>
                                        )}
                                    </div>
                                </div>
                                <div className="text-slate-700 leading-relaxed">{selectedPit.description}</div>
                                {selectedPit.trigger_hint && (
                                    <div className="text-indigo-700">触发回收时机提示：{selectedPit.trigger_hint}</div>
                                )}
                                {selectedPit.clues.length > 0 && (
                                    <div className="space-y-1 pt-1">
                                        <div className="font-semibold text-slate-600">跨话线索推进记录：</div>
                                        {selectedPit.clues.map((c, idx) => (
                                            <div key={idx} className="text-slate-600 pl-2 border-l-2 border-indigo-300">
                                                {c.episode_number ? `[第${c.episode_number}话] ` : ''}
                                                {c.text}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
