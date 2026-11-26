import { useMemo, useState } from 'react'
import { Tag, Empty, Button, RadioGroup } from '@douyinfe/semi-ui'
import { storageFileUrl } from '@/services/project'
import type { StoryGraphCharacterNode, StoryGraphEdge } from '@/services/project'

interface Props {
    nodes: StoryGraphCharacterNode[]
    edges: StoryGraphEdge[]
}

const ROLE_COLORS: Record<string, { stroke: string; bg: string; label: string }> = {
    protagonist: { stroke: '#4f46e5', bg: '#eef2ff', label: '主角' },
    main: { stroke: '#7c3aed', bg: '#f5f3ff', label: '主要角色' },
    antagonist: { stroke: '#e11d48', bg: '#fff1f2', label: '反派/对手' },
    support: { stroke: '#0d9488', bg: '#f0fdfa', label: '配角' },
}

const SVG_W = 860
const SVG_H = 540
const CX = SVG_W / 2
const CY = SVG_H / 2

export default function CharacterGraph({ nodes, edges }: Props) {
    const [limitMode, setLimitMode] = useState<'top' | 'all'>('top')
    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(nodes[0]?.id ?? null)
    const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null)

    const visibleNodes = useMemo(
        () => (limitMode === 'top' ? nodes.slice(0, 16) : nodes.slice(0, 40)),
        [nodes, limitMode],
    )

    const visibleIdSet = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])

    const visibleEdges = useMemo(
        () => edges.filter((e) => visibleIdSet.has(e.source) && visibleIdSet.has(e.target)).slice(0, 80),
        [edges, visibleIdSet],
    )

    // Deterministic dual-ring layout with mild repulsion so avatars stay clean & non-overlapping
    const positions = useMemo(() => {
        const pos = new Map<string, { x: number; y: number; r: number }>()
        const n = visibleNodes.length
        if (n === 0) return pos

        const maxApp = Math.max(...visibleNodes.map((v) => v.appearances || 1), 1)
        const innerCount = Math.min(n, Math.max(3, Math.min(6, Math.ceil(n * 0.35))))

        visibleNodes.forEach((node, idx) => {
            const ratio = (node.appearances || 1) / maxApp
            const r = Math.round(22 + ratio * 16)
            if (n === 1) {
                pos.set(node.id, { x: CX, y: CY, r: 36 })
                return
            }
            if (idx < innerCount) {
                const angle = (idx / innerCount) * Math.PI * 2 - Math.PI / 2
                const rad = innerCount <= 3 ? 115 : 132
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.15,
                    y: CY + Math.sin(angle) * rad * 0.92,
                    r,
                })
            } else {
                const outerIdx = idx - innerCount
                const outerTotal = Math.max(1, n - innerCount)
                const angle = (outerIdx / outerTotal) * Math.PI * 2 - Math.PI / 2 + 0.25
                const rad = 225
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.38,
                    y: CY + Math.sin(angle) * rad * 0.95,
                    r,
                })
            }
        })

        // Gentle relaxation pass to avoid label/node collisions
        const ids = visibleNodes.map((v) => v.id)
        for (let iter = 0; iter < 24; iter++) {
            for (let i = 0; i < ids.length; i++) {
                for (let j = i + 1; j < ids.length; j++) {
                    const a = pos.get(ids[i])!
                    const b = pos.get(ids[j])!
                    const dx = b.x - a.x
                    const dy = b.y - a.y
                    const dist = Math.hypot(dx, dy) || 1
                    const minDist = a.r + b.r + 36
                    if (dist < minDist) {
                        const push = (minDist - dist) * 0.25
                        const ux = dx / dist
                        const uy = dy / dist
                        a.x = Math.max(58, Math.min(SVG_W - 58, a.x - ux * push))
                        a.y = Math.max(54, Math.min(SVG_H - 64, a.y - uy * push))
                        b.x = Math.max(58, Math.min(SVG_W - 58, b.x + ux * push))
                        b.y = Math.max(54, Math.min(SVG_H - 64, b.y + uy * push))
                    }
                }
            }
        }
        return pos
    }, [visibleNodes])

    const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
    const maxWeight = useMemo(() => Math.max(...visibleEdges.map((e) => e.weight), 1), [visibleEdges])

    const connectedToHover = useMemo(() => {
        if (!hoveredId) return null
        const set = new Set<string>([hoveredId])
        visibleEdges.forEach((e) => {
            if (e.source === hoveredId) set.add(e.target)
            if (e.target === hoveredId) set.add(e.source)
        })
        return set
    }, [hoveredId, visibleEdges])

    const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) || null : null
    const selectedEdge = useMemo(() => {
        if (!selectedEdgeKey) return null
        return visibleEdges.find((e) => `${e.source}__${e.target}` === selectedEdgeKey) || null
    }, [selectedEdgeKey, visibleEdges])

    if (nodes.length === 0) {
        return <Empty description="暂未提取角色节点，请先对已导入章节执行「多模态剧情理解」。" />
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h3 className="text-base font-bold text-slate-900 m-0">人物共现与演进关系星图</h3>
                    <p className="text-xs text-slate-500 m-0 mt-0.5">
                        节点大小反映出场话数，连线粗细反映同场共现频次；点击角色头像查看服装与状态演进，点击连线查看交集名场面
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="hidden md:flex items-center gap-2 text-[11px] text-slate-600">
                        {Object.entries(ROLE_COLORS).map(([k, v]) => (
                            <span key={k} className="inline-flex items-center gap-1">
                                <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: v.stroke }} />
                                {v.label}
                            </span>
                        ))}
                    </div>
                    {nodes.length > 16 && (
                        <RadioGroup
                            type="button"
                            buttonSize="small"
                            value={limitMode}
                            onChange={(e) => setLimitMode(e.target.value as 'top' | 'all')}
                            options={[
                                { label: '核心 16 人', value: 'top' },
                                { label: `全部 (${Math.min(nodes.length, 40)})`, value: 'all' },
                            ]}
                        />
                    )}
                </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
                {/* Interactive SVG Graph */}
                <div className="xl:col-span-8 rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-50 via-white to-indigo-50/40 overflow-hidden relative">
                    <svg
                        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
                        className="w-full h-auto block select-none"
                        style={{ minHeight: 400 }}
                    >
                        <defs>
                            <radialGradient id="atlas-bg-glow" cx="50%" cy="50%" r="55%">
                                <stop offset="0%" stopColor="#6366f1" stopOpacity="0.09" />
                                <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
                            </radialGradient>
                            {visibleNodes.map((node) => {
                                const p = positions.get(node.id)
                                if (!p) return null
                                return (
                                    <clipPath key={`clip-${node.id}`} id={`avatar-clip-${node.id}`}>
                                        <circle cx={p.x} cy={p.y} r={p.r - 3} />
                                    </clipPath>
                                )
                            })}
                        </defs>

                        <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="url(#atlas-bg-glow)" />

                        {/* Edges */}
                        {visibleEdges.map((edge) => {
                            const a = positions.get(edge.source)
                            const b = positions.get(edge.target)
                            if (!a || !b) return null
                            const edgeKey = `${edge.source}__${edge.target}`
                            const isSelected = selectedEdgeKey === edgeKey
                            const isHighlighted =
                                isSelected ||
                                (hoveredId !== null && (edge.source === hoveredId || edge.target === hoveredId))
                            const dimmed = hoveredId !== null && !isHighlighted
                            const strokeWidth = 1.4 + (edge.weight / maxWeight) * 4.2
                            const mx = (a.x + b.x) / 2
                            const my = (a.y + b.y) / 2
                            return (
                                <g
                                    key={edgeKey}
                                    className="cursor-pointer"
                                    onClick={() => {
                                        setSelectedEdgeKey(edgeKey)
                                        setSelectedNodeId(null)
                                    }}
                                >
                                    {/* Wide invisible hit target */}
                                    <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={14} />
                                    <line
                                        x1={a.x}
                                        y1={a.y}
                                        x2={b.x}
                                        y2={b.y}
                                        stroke={isSelected ? '#4f46e5' : isHighlighted ? '#6366f1' : '#94a3b8'}
                                        strokeWidth={isSelected ? strokeWidth + 1.5 : strokeWidth}
                                        strokeOpacity={dimmed ? 0.12 : isHighlighted ? 0.85 : 0.38}
                                        strokeLinecap="round"
                                    />
                                    {(isHighlighted || edge.weight >= Math.max(2, Math.ceil(maxWeight * 0.6))) && (
                                        <g opacity={dimmed ? 0.15 : 1}>
                                            <circle cx={mx} cy={my} r={10} fill="#ffffff" stroke="#c7d2fe" strokeWidth={1.2} />
                                            <text
                                                x={mx}
                                                y={my + 3.5}
                                                textAnchor="middle"
                                                fontSize={10}
                                                fontWeight={700}
                                                fill="#4338ca"
                                            >
                                                {edge.weight}
                                            </text>
                                        </g>
                                    )}
                                </g>
                            )
                        })}

                        {/* Character Nodes */}
                        {visibleNodes.map((node) => {
                            const p = positions.get(node.id)
                            if (!p) return null
                            const roleStyle = ROLE_COLORS[node.role] || ROLE_COLORS.support
                            const isSelected = selectedNodeId === node.id
                            const dimmed = connectedToHover !== null && !connectedToHover.has(node.id)
                            const initials = node.name.slice(0, 2)
                            return (
                                <g
                                    key={node.id}
                                    className="cursor-pointer"
                                    opacity={dimmed ? 0.25 : 1}
                                    onMouseEnter={() => setHoveredId(node.id)}
                                    onMouseLeave={() => setHoveredId(null)}
                                    onClick={() => {
                                        setSelectedNodeId(node.id)
                                        setSelectedEdgeKey(null)
                                    }}
                                >
                                    {isSelected && (
                                        <circle
                                            cx={p.x}
                                            cy={p.y}
                                            r={p.r + 6}
                                            fill="none"
                                            stroke={roleStyle.stroke}
                                            strokeWidth={2.5}
                                            strokeDasharray="5 3"
                                        />
                                    )}
                                    <circle
                                        cx={p.x}
                                        cy={p.y}
                                        r={p.r}
                                        fill={roleStyle.bg}
                                        stroke={roleStyle.stroke}
                                        strokeWidth={isSelected ? 3.2 : 2.2}
                                    />
                                    {node.avatar_path ? (
                                        <image
                                            href={storageFileUrl(node.avatar_path)}
                                            x={p.x - (p.r - 3)}
                                            y={p.y - (p.r - 3)}
                                            width={(p.r - 3) * 2}
                                            height={(p.r - 3) * 2}
                                            preserveAspectRatio="xMidYMid slice"
                                            clipPath={`url(#avatar-clip-${node.id})`}
                                        />
                                    ) : (
                                        <text
                                            x={p.x}
                                            y={p.y + 5}
                                            textAnchor="middle"
                                            fontSize={13}
                                            fontWeight={700}
                                            fill={roleStyle.stroke}
                                        >
                                            {initials}
                                        </text>
                                    )}

                                    {/* Appearance count badge */}
                                    <circle
                                        cx={p.x + p.r * 0.72}
                                        cy={p.y - p.r * 0.72}
                                        r={9.5}
                                        fill={roleStyle.stroke}
                                        stroke="#ffffff"
                                        strokeWidth={1.5}
                                    />
                                    <text
                                        x={p.x + p.r * 0.72}
                                        y={p.y - p.r * 0.72 + 3.5}
                                        textAnchor="middle"
                                        fontSize={9.5}
                                        fontWeight={700}
                                        fill="#ffffff"
                                    >
                                        {node.appearances}
                                    </text>

                                    {/* Label pill */}
                                    <rect
                                        x={p.x - Math.min(62, Math.max(30, node.name.length * 8.5 + 14))}
                                        y={p.y + p.r + 6}
                                        width={Math.min(124, Math.max(60, node.name.length * 17 + 28))}
                                        height={22}
                                        rx={11}
                                        fill="#ffffff"
                                        fillOpacity={0.98}
                                        stroke={isSelected ? roleStyle.stroke : '#cbd5e1'}
                                        strokeWidth={isSelected ? 1.5 : 1}
                                    />
                                    <text
                                        x={p.x}
                                        y={p.y + p.r + 20.5}
                                        textAnchor="middle"
                                        fontSize={11.5}
                                        fontWeight={700}
                                        fill="#0f172a"
                                    >
                                        {node.name.length > 7 ? `${node.name.slice(0, 6)}…` : node.name}
                                    </text>
                                </g>
                            )
                        })}
                    </svg>
                </div>

                {/* Right Side Inspector: Character Evolution OR Edge Co-occurrence */}
                <div className="xl:col-span-4 rounded-2xl border border-slate-200 bg-white p-4 space-y-4 max-h-[540px] overflow-y-auto">
                    {selectedNode ? (
                        <>
                            <div className="flex items-start gap-3 pb-3 border-b border-slate-100">
                                {selectedNode.avatar_path ? (
                                    <img
                                        src={storageFileUrl(selectedNode.avatar_path)}
                                        alt={selectedNode.name}
                                        className="w-16 h-16 rounded-xl object-cover border border-slate-200 shrink-0"
                                    />
                                ) : (
                                    <div className="w-16 h-16 rounded-xl bg-indigo-50 text-indigo-700 font-bold text-lg flex items-center justify-center shrink-0">
                                        {selectedNode.name.slice(0, 2)}
                                    </div>
                                )}
                                <div className="min-w-0 flex-1 space-y-1">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-extrabold text-base text-slate-900">{selectedNode.name}</span>
                                        <Tag size="small" color="indigo">
                                            {(ROLE_COLORS[selectedNode.role] || ROLE_COLORS.support).label}
                                        </Tag>
                                        <Tag size="small" color="cyan">
                                            出场 {selectedNode.appearances} 话
                                        </Tag>
                                    </div>
                                    {selectedNode.aliases.length > 0 && (
                                        <div className="text-[11px] text-slate-500">
                                            别名：{selectedNode.aliases.join(' / ')}
                                        </div>
                                    )}
                                </div>
                            </div>

                            {selectedNode.description && (
                                <div className="text-xs text-slate-700 leading-relaxed bg-slate-50 rounded-xl p-3 border border-slate-100">
                                    {selectedNode.description}
                                </div>
                            )}

                            {selectedNode.speech_style && (
                                <div className="space-y-1">
                                    <div className="text-[11px] font-bold text-slate-500 uppercase">台词口癖与说话风格</div>
                                    <div className="text-xs text-indigo-900 bg-indigo-50/70 rounded-lg px-3 py-2 border border-indigo-100">
                                        {selectedNode.speech_style}
                                    </div>
                                </div>
                            )}

                            {selectedNode.visual_tags.length > 0 && (
                                <div className="space-y-1.5">
                                    <div className="text-[11px] font-bold text-slate-500 uppercase">视觉特征锚点</div>
                                    <div className="flex flex-wrap gap-1.5">
                                        {selectedNode.visual_tags.map((t, i) => (
                                            <Tag key={i} size="small" color="grey">
                                                {t}
                                            </Tag>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {selectedNode.outfits.length > 0 && (
                                <div className="space-y-1.5">
                                    <div className="text-[11px] font-bold text-slate-500 uppercase">
                                        已收录服装造型 ({selectedNode.outfits.length})
                                    </div>
                                    <div className="grid grid-cols-2 gap-2">
                                        {selectedNode.outfits.map((of) => (
                                            <div key={of.id} className="rounded-lg border border-slate-200 p-2 bg-slate-50 flex items-center gap-2">
                                                {of.image_path && (
                                                    <img
                                                        src={storageFileUrl(of.image_path)}
                                                        alt={of.name}
                                                        className="w-9 h-9 rounded object-cover shrink-0"
                                                    />
                                                )}
                                                <div className="min-w-0">
                                                    <div className="text-xs font-semibold text-slate-800 truncate">{of.name}</div>
                                                    {of.description && (
                                                        <div className="text-[10px] text-slate-500 line-clamp-2">{of.description}</div>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div className="space-y-2">
                                <div className="text-[11px] font-bold text-slate-500 uppercase">
                                    状态演进轨迹 ({selectedNode.state_timeline.length})
                                </div>
                                {selectedNode.state_timeline.length === 0 ? (
                                    <div className="text-xs text-slate-400">暂无跨话状态变更记录</div>
                                ) : (
                                    <div className="space-y-2 border-l-2 border-indigo-200 pl-3 ml-1">
                                        {selectedNode.state_timeline.map((st, idx) => (
                                            <div key={idx} className="text-xs space-y-0.5 relative">
                                                <span className="w-2 h-2 rounded-full bg-indigo-500 absolute -left-[17px] top-1.5" />
                                                <div className="font-semibold text-slate-800">
                                                    第 {st.episode_label} 话 · {st.attribute}
                                                </div>
                                                <div className="text-slate-600">
                                                    {st.before ? `${st.before} → ` : ''}
                                                    <span className="text-emerald-700 font-medium">{st.after}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </>
                    ) : selectedEdge ? (
                        <div className="space-y-4">
                            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                                <div className="font-bold text-sm text-slate-900">
                                    {nodeById.get(selectedEdge.source)?.name || '角色A'} ↔{' '}
                                    {nodeById.get(selectedEdge.target)?.name || '角色B'}
                                </div>
                                <Tag color="indigo">共现权重 {selectedEdge.weight}</Tag>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {selectedEdge.shared_episodes.map((epNo) => (
                                    <Tag key={epNo} size="small" color="blue">
                                        第 {epNo} 话同场
                                    </Tag>
                                ))}
                            </div>
                            <div className="space-y-2">
                                <div className="text-[11px] font-bold text-slate-500 uppercase">
                                    关键交集事件 ({selectedEdge.moments.length})
                                </div>
                                {selectedEdge.moments.length === 0 ? (
                                    <div className="text-xs text-slate-500">双方在以上章节中同场出场。</div>
                                ) : (
                                    selectedEdge.moments.map((m, idx) => (
                                        <div key={idx} className="rounded-xl bg-slate-50 border border-slate-200 p-3 space-y-1 text-xs">
                                            <div className="flex items-center justify-between">
                                                <span className="font-bold text-indigo-700">第 {m.episode_label} 话</span>
                                                {m.location && <span className="text-slate-400">{m.location}</span>}
                                            </div>
                                            <div className="text-slate-700 leading-relaxed">{m.description}</div>
                                        </div>
                                    ))
                                )}
                            </div>
                            <Button
                                size="small"
                                onClick={() => {
                                    setSelectedEdgeKey(null)
                                    setSelectedNodeId(selectedEdge.source)
                                }}
                            >
                                查看 {nodeById.get(selectedEdge.source)?.name} 详情
                            </Button>
                        </div>
                    ) : (
                        <Empty description="点击星图中的任意角色头像或连线查看详情" />
                    )}
                </div>
            </div>
        </div>
    )
}
