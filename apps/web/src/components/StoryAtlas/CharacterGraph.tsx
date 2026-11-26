import { useMemo, useRef, useState } from 'react'
import { Empty, Input, Select, Toast } from '@douyinfe/semi-ui'
import { assetService, storageFileUrl } from '@/services/project'
import type { StoryGraphCharacterNode, StoryGraphEdge } from '@/services/project'
import ResizableInspector from '@/components/ResizableInspector'
import { IconZoomIn, IconZoomOut, IconFit } from '@/components/StudioIcons'

interface Props {
    nodes: StoryGraphCharacterNode[]
    edges: StoryGraphEdge[]
    onStatusUpdated?: () => void
}

const ROLE_LABELS: Record<string, string> = {
    protagonist: '主角',
    main: '主要角色',
    antagonist: '对手 / 反派',
    support: '配角',
}

const VITAL_LABELS: Record<string, string> = {
    alive: '存活',
    injured: '重伤 / 失能',
    missing: '失踪',
    sealed: '封印',
    deceased: '已故',
}

const CANVAS_W = 1040
const CANVAS_H = 660
const CX = CANVAS_W / 2
const CY = CANVAS_H / 2

export default function CharacterGraph({ nodes, edges, onStatusUpdated }: Props) {
    const [search, setSearch] = useState('')
    const [roleFilter, setRoleFilter] = useState<string>('all')
    const [vitalFilter, setVitalFilter] = useState<string>('all')
    const [focusMode, setFocusMode] = useState(false)

    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(nodes[0]?.id ?? null)
    const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null)
    const [savingStatus, setSavingStatus] = useState(false)

    // Interactive pan / zoom / draggable node offsets
    const [zoom, setZoom] = useState(1)
    const [pan, setPan] = useState({ x: 0, y: 0 })
    const [nodeOffsets, setNodeOffsets] = useState<Record<string, { x: number; y: number }>>({})

    const svgRef = useRef<SVGSVGElement | null>(null)
    const panRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
    const dragNodeRef = useRef<{ id: string; startX: number; startY: number; origX: number; origY: number } | null>(null)

    const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

    const filteredNodes = useMemo(() => {
        const q = search.trim().toLowerCase()
        return nodes.filter((n) => {
            if (roleFilter !== 'all' && n.role !== roleFilter) return false
            if (vitalFilter !== 'all' && (n.vital_status || 'alive') !== vitalFilter) return false
            if (q) {
                const hay = [n.name, ...n.aliases, n.description].join(' ').toLowerCase()
                if (!hay.includes(q)) return false
            }
            return true
        })
    }, [nodes, search, roleFilter, vitalFilter])

    const visibleIdSet = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes])

    const visibleEdges = useMemo(
        () => edges.filter((e) => visibleIdSet.has(e.source) && visibleIdSet.has(e.target)),
        [edges, visibleIdSet],
    )

    // Base deterministic dual-ring layout
    const basePositions = useMemo(() => {
        const pos = new Map<string, { x: number; y: number; r: number }>()
        const n = filteredNodes.length
        if (n === 0) return pos
        const maxApp = Math.max(...filteredNodes.map((v) => v.appearances || 1), 1)
        const innerCount = Math.min(n, Math.max(3, Math.min(6, Math.ceil(n * 0.38))))

        filteredNodes.forEach((node, idx) => {
            const ratio = (node.appearances || 1) / maxApp
            const r = Math.round(24 + ratio * 15)
            if (n === 1) {
                pos.set(node.id, { x: CX, y: CY, r: 38 })
                return
            }
            if (idx < innerCount) {
                const angle = (idx / innerCount) * Math.PI * 2 - Math.PI / 2
                const rad = innerCount <= 3 ? 130 : 155
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.22,
                    y: CY + Math.sin(angle) * rad * 0.92,
                    r,
                })
            } else {
                const outerIdx = idx - innerCount
                const outerTotal = Math.max(1, n - innerCount)
                const angle = (outerIdx / outerTotal) * Math.PI * 2 - Math.PI / 2 + 0.3
                const rad = 255
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.32,
                    y: CY + Math.sin(angle) * rad * 0.92,
                    r,
                })
            }
        })

        const ids = filteredNodes.map((v) => v.id)
        for (let iter = 0; iter < 24; iter++) {
            for (let i = 0; i < ids.length; i++) {
                for (let j = i + 1; j < ids.length; j++) {
                    const a = pos.get(ids[i])!
                    const b = pos.get(ids[j])!
                    const dx = b.x - a.x
                    const dy = b.y - a.y
                    const dist = Math.hypot(dx, dy) || 1
                    const minDist = a.r + b.r + 56
                    if (dist < minDist) {
                        const push = (minDist - dist) * 0.25
                        const ux = dx / dist
                        const uy = dy / dist
                        a.x -= ux * push
                        a.y -= uy * push
                        b.x += ux * push
                        b.y += uy * push
                    }
                }
            }
        }
        return pos
    }, [filteredNodes])

    const getPos = (id: string) => {
        const base = basePositions.get(id)
        if (!base) return null
        const off = nodeOffsets[id]
        return off ? { x: base.x + off.x, y: base.y + off.y, r: base.r } : base
    }

    const maxWeight = useMemo(() => Math.max(...visibleEdges.map((e) => e.weight), 1), [visibleEdges])

    const focusAnchorId = hoveredId || (focusMode ? selectedNodeId : null)
    const connectedSet = useMemo(() => {
        if (!focusAnchorId) return null
        const s = new Set<string>([focusAnchorId])
        visibleEdges.forEach((e) => {
            if (e.source === focusAnchorId) s.add(e.target)
            if (e.target === focusAnchorId) s.add(e.source)
        })
        return s
    }, [focusAnchorId, visibleEdges])

    const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) || null : null
    const selectedEdge = useMemo(() => {
        if (!selectedEdgeKey) return null
        return visibleEdges.find((e) => `${e.source}__${e.target}` === selectedEdgeKey) || null
    }, [selectedEdgeKey, visibleEdges])

    const selectedNeighbors = useMemo(() => {
        if (!selectedNode) return []
        return edges
            .filter((e) => e.source === selectedNode.id || e.target === selectedNode.id)
            .map((e) => {
                const otherId = e.source === selectedNode.id ? e.target : e.source
                return { edge: e, other: nodeById.get(otherId) }
            })
            .filter((x) => Boolean(x.other))
            .sort((a, b) => b.edge.weight - a.edge.weight)
    }, [selectedNode, edges, nodeById])

    const handleWheel = (e: React.WheelEvent) => {
        e.preventDefault()
        const delta = e.deltaY < 0 ? 0.1 : -0.1
        setZoom((z) => Math.max(0.45, Math.min(2.4, Number((z + delta).toFixed(2)))))
    }

    const handleBgPointerDown = (e: React.PointerEvent) => {
        panRef.current = { startX: e.clientX, startY: e.clientY, origX: pan.x, origY: pan.y }
        ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    }

    const handleBgPointerMove = (e: React.PointerEvent) => {
        if (dragNodeRef.current) {
            const dx = (e.clientX - dragNodeRef.current.startX) / zoom
            const dy = (e.clientY - dragNodeRef.current.startY) / zoom
            const nid = dragNodeRef.current.id
            setNodeOffsets((prev) => ({
                ...prev,
                [nid]: { x: dragNodeRef.current!.origX + dx, y: dragNodeRef.current!.origY + dy },
            }))
            return
        }
        if (panRef.current) {
            setPan({
                x: panRef.current.origX + (e.clientX - panRef.current.startX),
                y: panRef.current.origY + (e.clientY - panRef.current.startY),
            })
        }
    }

    const handleBgPointerUp = () => {
        panRef.current = null
        dragNodeRef.current = null
    }

    const handleNodePointerDown = (e: React.PointerEvent, nodeId: string) => {
        e.stopPropagation()
        setSelectedNodeId(nodeId)
        setSelectedEdgeKey(null)
        const off = nodeOffsets[nodeId] || { x: 0, y: 0 }
        dragNodeRef.current = { id: nodeId, startX: e.clientX, startY: e.clientY, origX: off.x, origY: off.y }
        svgRef.current?.setPointerCapture(e.pointerId)
    }

    const handleOverrideStatus = async (node: StoryGraphCharacterNode, nextVal: string) => {
        setSavingStatus(true)
        try {
            const fullAsset = await assetService.get(node.id)
            const nextTags = { ...(fullAsset.tags || {}) }
            if (nextVal === 'auto') {
                delete nextTags.vital_status_override
            } else {
                nextTags.vital_status_override = nextVal
            }
            await assetService.update(node.id, { tags: nextTags })
            Toast.success(
                nextVal === 'auto'
                    ? `已恢复 ${node.name} 为剧情自动推导状态`
                    : `已锁定 ${node.name} 为「${VITAL_LABELS[nextVal] || nextVal}」`,
            )
            onStatusUpdated?.()
        } catch {
            Toast.error('更新角色生命状态失败')
        } finally {
            setSavingStatus(false)
        }
    }

    if (nodes.length === 0) {
        return (
            <div className="flex-1 flex items-center justify-center p-12">
                <Empty description="暂未提取角色节点，请先对章节执行多模态剧情理解。" />
            </div>
        )
    }

    return (
        <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* IMMERSIVE GRAPH WORKSPACE */}
            <div className="flex-1 min-w-0 min-h-0 relative mf-canvas-grid overflow-hidden">
                {/* Floating Top-Left Filter & Search Bar */}
                <div
                    className="absolute top-3 left-3 z-20 flex flex-wrap items-center gap-2 p-1.5 rounded-md border"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <Input
                        size="small"
                        value={search}
                        onChange={setSearch}
                        placeholder="检索角色或别名..."
                        style={{ width: 156 }}
                    />
                    <Select
                        size="small"
                        value={roleFilter}
                        onChange={(v) => setRoleFilter(String(v))}
                        style={{ width: 118 }}
                    >
                        <Select.Option value="all">定位: 全部</Select.Option>
                        <Select.Option value="protagonist">定位: 主角</Select.Option>
                        <Select.Option value="main">定位: 主要</Select.Option>
                        <Select.Option value="support">定位: 配角</Select.Option>
                        <Select.Option value="antagonist">定位: 反派</Select.Option>
                    </Select>
                    <Select
                        size="small"
                        value={vitalFilter}
                        onChange={(v) => setVitalFilter(String(v))}
                        style={{ width: 114 }}
                    >
                        <Select.Option value="all">状态: 全部</Select.Option>
                        <Select.Option value="alive">状态: 存活</Select.Option>
                        <Select.Option value="deceased">状态: 已故</Select.Option>
                        <Select.Option value="injured">状态: 重伤</Select.Option>
                        <Select.Option value="missing">状态: 失踪</Select.Option>
                        <Select.Option value="sealed">状态: 封印</Select.Option>
                    </Select>
                    <button
                        type="button"
                        onClick={() => setFocusMode((v) => !v)}
                        className="h-6 px-2 rounded border text-[11px] cursor-pointer transition-colors"
                        style={{
                            backgroundColor: focusMode ? 'var(--accent-subtle)' : 'transparent',
                            borderColor: focusMode ? 'var(--accent)' : 'var(--border)',
                            color: focusMode ? 'var(--accent)' : 'var(--text-secondary)',
                        }}
                    >
                        聚焦关联
                    </button>
                    <span className="text-[11px] font-mono px-1.5" style={{ color: 'var(--text-muted)' }}>
                        {filteredNodes.length} 节点 · {visibleEdges.length} 连线
                    </span>
                </div>

                {/* Interactive Pan/Zoom/Drag SVG Canvas */}
                <svg
                    ref={svgRef}
                    onWheel={handleWheel}
                    onPointerDown={handleBgPointerDown}
                    onPointerMove={handleBgPointerMove}
                    onPointerUp={handleBgPointerUp}
                    viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
                    className="w-full h-full block cursor-grab active:cursor-grabbing select-none"
                >
                    <defs>
                        {/* Authentic Monochrome Manga Ink Portrait Filter */}
                        <filter id="manga-bw">
                            <feColorMatrix type="saturate" values="0" />
                            <feComponentTransfer>
                                <feFuncR type="linear" slope="1.08" intercept="-0.03" />
                                <feFuncG type="linear" slope="1.08" intercept="-0.03" />
                                <feFuncB type="linear" slope="1.08" intercept="-0.03" />
                            </feComponentTransfer>
                        </filter>
                        {filteredNodes.map((node) => {
                            const p = getPos(node.id)
                            if (!p) return null
                            return (
                                <clipPath key={`clip-${node.id}`} id={`ink-clip-${node.id}`}>
                                    <circle cx={p.x} cy={p.y} r={p.r - 2.5} />
                                </clipPath>
                            )
                        })}
                    </defs>

                    <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`} style={{ transformOrigin: `${CX}px ${CY}px` }}>
                        {/* Subtle Technical Reference Rings */}
                        <ellipse cx={CX} cy={CY} rx={175} ry={135} fill="none" stroke="var(--border)" strokeOpacity={0.35} strokeDasharray="3 6" />
                        <ellipse cx={CX} cy={CY} rx={325} ry={225} fill="none" stroke="var(--border)" strokeOpacity={0.25} strokeDasharray="3 8" />

                        {/* Co-occurrence Edges */}
                        {visibleEdges.map((edge) => {
                            const a = getPos(edge.source)
                            const b = getPos(edge.target)
                            if (!a || !b) return null
                            const edgeKey = `${edge.source}__${edge.target}`
                            const isSelected = selectedEdgeKey === edgeKey
                            const isLinked =
                                isSelected ||
                                (focusAnchorId !== null && (edge.source === focusAnchorId || edge.target === focusAnchorId))
                            const dimmed = connectedSet !== null && !isLinked
                            const strokeWidth = 1 + (edge.weight / maxWeight) * 2.8
                            const mx = (a.x + b.x) / 2
                            const my = (a.y + b.y) / 2

                            return (
                                <g
                                    key={edgeKey}
                                    className="cursor-pointer"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setSelectedEdgeKey(edgeKey)
                                        setSelectedNodeId(null)
                                    }}
                                >
                                    <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={14} />
                                    <line
                                        x1={a.x}
                                        y1={a.y}
                                        x2={b.x}
                                        y2={b.y}
                                        stroke={isSelected || isLinked ? '#E64B35' : '#71717A'}
                                        strokeWidth={isSelected ? strokeWidth + 1 : strokeWidth}
                                        strokeOpacity={dimmed ? 0.08 : isSelected || isLinked ? 0.85 : 0.36}
                                    />
                                    {(isLinked || edge.weight >= Math.max(3, Math.ceil(maxWeight * 0.6))) && (
                                        <g opacity={dimmed ? 0.1 : 1}>
                                            <rect
                                                x={mx - 11}
                                                y={my - 8}
                                                width={22}
                                                height={16}
                                                rx={3}
                                                fill="var(--bg-panel)"
                                                stroke={isSelected || isLinked ? '#E64B35' : 'var(--border)'}
                                                strokeWidth={1}
                                            />
                                            <text
                                                x={mx}
                                                y={my + 3.5}
                                                textAnchor="middle"
                                                fontSize={9.5}
                                                fontFamily="ui-monospace, monospace"
                                                fontWeight={600}
                                                fill={isSelected || isLinked ? '#E64B35' : 'var(--text-secondary)'}
                                            >
                                                {edge.weight}
                                            </text>
                                        </g>
                                    )}
                                </g>
                            )
                        })}

                        {/* Monochrome Manga Portrait Nodes */}
                        {filteredNodes.map((node) => {
                            const p = getPos(node.id)
                            if (!p) return null
                            const isSelected = selectedNodeId === node.id
                            const isDeceased = node.vital_status === 'deceased'
                            const dimmed = connectedSet !== null && !connectedSet.has(node.id)
                            const labelText = node.name.length > 7 ? `${node.name.slice(0, 6)}…` : node.name
                            const pillW = Math.min(126, Math.max(58, labelText.length * 13 + 22))

                            return (
                                <g
                                    key={node.id}
                                    className="cursor-move"
                                    opacity={dimmed ? 0.18 : 1}
                                    onMouseEnter={() => setHoveredId(node.id)}
                                    onMouseLeave={() => setHoveredId(null)}
                                    onPointerDown={(e) => handleNodePointerDown(e, node.id)}
                                >
                                    {/* Selected Vermilion Editorial Frame Ring */}
                                    {isSelected && (
                                        <circle
                                            cx={p.x}
                                            cy={p.y}
                                            r={p.r + 5}
                                            fill="none"
                                            stroke="#E64B35"
                                            strokeWidth={1.5}
                                            strokeDasharray="4 3"
                                        />
                                    )}

                                    <circle
                                        cx={p.x}
                                        cy={p.y}
                                        r={p.r}
                                        fill="var(--paper)"
                                        stroke={isSelected ? '#E64B35' : isDeceased ? '#71717A' : '#52525B'}
                                        strokeWidth={isSelected ? 2.2 : 1.5}
                                        strokeDasharray={isDeceased ? '3 3' : undefined}
                                    />

                                    {node.avatar_path ? (
                                        <image
                                            href={storageFileUrl(node.avatar_path)}
                                            x={p.x - (p.r - 2.5)}
                                            y={p.y - (p.r - 2.5)}
                                            width={(p.r - 2.5) * 2}
                                            height={(p.r - 2.5) * 2}
                                            preserveAspectRatio="xMidYMid slice"
                                            clipPath={`url(#ink-clip-${node.id})`}
                                            filter="url(#manga-bw)"
                                            opacity={isDeceased ? 0.5 : 0.96}
                                        />
                                    ) : (
                                        <text
                                            x={p.x}
                                            y={p.y + 4.5}
                                            textAnchor="middle"
                                            fontSize={12}
                                            fontWeight={700}
                                            fill="#18181B"
                                        >
                                            {node.name.slice(0, 2)}
                                        </text>
                                    )}

                                    {/* Subtle diagonal editorial redline strike on deceased portrait */}
                                    {isDeceased && (
                                        <line
                                            x1={p.x - p.r * 0.55}
                                            y1={p.y + p.r * 0.55}
                                            x2={p.x + p.r * 0.55}
                                            y2={p.y - p.r * 0.55}
                                            stroke="#E64B35"
                                            strokeWidth={1.6}
                                            strokeOpacity={0.85}
                                        />
                                    )}

                                    {/* Crisp Square-Rounded Index Tag (Ep count or 已故) */}
                                    <rect
                                        x={p.x + p.r * 0.45}
                                        y={p.y - p.r - 2}
                                        width={isDeceased ? 28 : 20}
                                        height={15}
                                        rx={3}
                                        fill={isDeceased ? '#E64B35' : 'var(--bg-panel)'}
                                        stroke={isDeceased ? '#E64B35' : 'var(--border)'}
                                        strokeWidth={1}
                                    />
                                    <text
                                        x={p.x + p.r * 0.45 + (isDeceased ? 14 : 10)}
                                        y={p.y - p.r + 8.5}
                                        textAnchor="middle"
                                        fontSize={8.5}
                                        fontFamily="ui-monospace, monospace"
                                        fontWeight={700}
                                        fill={isDeceased ? '#FFFFFF' : 'var(--text-primary)'}
                                    >
                                        {isDeceased ? '已故' : node.appearances}
                                    </text>

                                    {/* Clean Editorial Nameplate (4px radius) */}
                                    <rect
                                        x={p.x - pillW / 2}
                                        y={p.y + p.r + 6}
                                        width={pillW}
                                        height={20}
                                        rx={4}
                                        fill="var(--bg-panel)"
                                        stroke={isSelected ? '#E64B35' : 'var(--border)'}
                                        strokeWidth={1}
                                    />
                                    <text
                                        x={p.x}
                                        y={p.y + p.r + 19.5}
                                        textAnchor="middle"
                                        fontSize={11}
                                        fontWeight={600}
                                        fill={isDeceased ? 'var(--text-muted)' : 'var(--text-primary)'}
                                    >
                                        {labelText}
                                    </text>
                                </g>
                            )
                        })}
                    </g>
                </svg>

                {/* Floating Bottom-Left Zoom Controls */}
                <div
                    className="absolute bottom-3.5 left-3.5 z-20 flex items-center gap-1 p-1 rounded-md border"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <button
                        type="button"
                        title="缩小"
                        onClick={() => setZoom((z) => Math.max(0.45, Number((z - 0.15).toFixed(2))))}
                        className="w-7 h-7 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconZoomOut size={14} />
                    </button>
                    <span className="w-10 text-center text-[11px] font-mono" style={{ color: 'var(--text-primary)' }}>
                        {Math.round(zoom * 100)}%
                    </span>
                    <button
                        type="button"
                        title="放大"
                        onClick={() => setZoom((z) => Math.min(2.4, Number((z + 0.15).toFixed(2))))}
                        className="w-7 h-7 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconZoomIn size={14} />
                    </button>
                    <button
                        type="button"
                        title="重置视图与节点位置"
                        onClick={() => {
                            setZoom(1)
                            setPan({ x: 0, y: 0 })
                            setNodeOffsets({})
                        }}
                        className="w-7 h-7 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconFit size={14} />
                    </button>
                </div>
            </div>

            {/* RIGHT COLLAPSIBLE RESIZABLE CHARACTER INSPECTOR */}
            <ResizableInspector
                title={selectedNode ? '角色档案' : selectedEdge ? '共现关系' : '图谱检查器'}
                subtitle={selectedNode ? ROLE_LABELS[selectedNode.role] || selectedNode.role : undefined}
            >
                {selectedNode ? (
                    <div className="space-y-4">
                        {/* Editorial Portrait & Header */}
                        <div className="flex items-start gap-3 pb-3.5 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div
                                className="w-16 h-16 rounded border overflow-hidden shrink-0"
                                style={{ backgroundColor: 'var(--paper)', borderColor: 'var(--border)' }}
                            >
                                {selectedNode.avatar_path ? (
                                    <img
                                        src={storageFileUrl(selectedNode.avatar_path)}
                                        alt={selectedNode.name}
                                        className="w-full h-full object-cover grayscale contrast-110"
                                        style={{ opacity: selectedNode.vital_status === 'deceased' ? 0.55 : 1 }}
                                    />
                                ) : (
                                    <div className="w-full h-full flex items-center justify-center font-editorial font-bold text-base text-[#18181B]">
                                        {selectedNode.name.slice(0, 2)}
                                    </div>
                                )}
                            </div>
                            <div className="min-w-0 flex-1 space-y-1">
                                <h3 className="font-editorial text-base font-bold m-0" style={{ color: 'var(--text-primary)' }}>
                                    {selectedNode.name}
                                </h3>
                                <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono" style={{ color: 'var(--text-secondary)' }}>
                                    <span>{ROLE_LABELS[selectedNode.role] || selectedNode.role}</span>
                                    <span style={{ color: 'var(--border)' }}>·</span>
                                    <span>登场 {selectedNode.appearances} 话</span>
                                </div>
                                {selectedNode.aliases.length > 0 && (
                                    <div className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                                        别名：{selectedNode.aliases.join(' / ')}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Vital Status & Author Override */}
                        <div className="space-y-2 pb-3.5 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div className="flex items-center justify-between text-[11px]">
                                <span className="uppercase tracking-wider font-semibold" style={{ color: 'var(--text-muted)' }}>
                                    生命状态
                                </span>
                                <span
                                    className="font-mono font-semibold px-1.5 py-0.5 rounded-[3px] border"
                                    style={{
                                        borderColor:
                                            selectedNode.vital_status === 'deceased' ? 'var(--accent)' : 'var(--border)',
                                        color:
                                            selectedNode.vital_status === 'deceased'
                                                ? 'var(--accent)'
                                                : 'var(--text-primary)',
                                        backgroundColor:
                                            selectedNode.vital_status === 'deceased'
                                                ? 'var(--accent-subtle)'
                                                : 'var(--bg-app)',
                                    }}
                                >
                                    {VITAL_LABELS[selectedNode.vital_status || 'alive'] || selectedNode.vital_status}
                                    {selectedNode.vital_status_episode ? ` · Ep.${selectedNode.vital_status_episode}` : ''}
                                </span>
                            </div>
                            {selectedNode.vital_status_note && (
                                <div className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                    {selectedNode.vital_status_note}
                                </div>
                            )}
                            <Select
                                size="small"
                                loading={savingStatus}
                                style={{ width: '100%' }}
                                value={selectedNode.vital_status_override || 'auto'}
                                onChange={(val) => handleOverrideStatus(selectedNode, String(val || 'auto'))}
                            >
                                <Select.Option value="auto">状态来源：剧情自动迭代</Select.Option>
                                <Select.Option value="alive">手动锁定：存活</Select.Option>
                                <Select.Option value="injured">手动锁定：重伤 / 失能</Select.Option>
                                <Select.Option value="missing">手动锁定：失踪</Select.Option>
                                <Select.Option value="sealed">手动锁定：封印</Select.Option>
                                <Select.Option value="deceased">手动锁定：已故（续画禁活）</Select.Option>
                            </Select>
                        </div>

                        {/* Bio & Speech Style */}
                        {selectedNode.description && (
                            <div className="space-y-1 pb-3.5 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                                <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                    人物设定
                                </div>
                                <p className="text-xs leading-relaxed m-0" style={{ color: 'var(--text-secondary)' }}>
                                    {selectedNode.description}
                                </p>
                                {selectedNode.speech_style && (
                                    <div
                                        className="mt-2 pt-2 border-t text-xs"
                                        style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}
                                    >
                                        <span style={{ color: 'var(--text-muted)' }}>语态口癖：</span>
                                        {selectedNode.speech_style}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Relationship Links */}
                        {selectedNeighbors.length > 0 && (
                            <div className="space-y-1.5 pb-3.5 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                                <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                    关联人物 ({selectedNeighbors.length})
                                </div>
                                <div className="space-y-1">
                                    {selectedNeighbors.slice(0, 8).map(({ edge, other }) => (
                                        <button
                                            key={other!.id}
                                            type="button"
                                            onClick={() => {
                                                setSelectedEdgeKey(`${edge.source}__${edge.target}`)
                                                setSelectedNodeId(null)
                                            }}
                                            className="w-full px-2 py-1.5 rounded border-0 bg-transparent hover:bg-[var(--bg-hover)] flex items-center justify-between text-xs cursor-pointer transition-colors"
                                        >
                                            <span style={{ color: 'var(--text-primary)' }}>{other!.name}</span>
                                            <span className="font-mono text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                                共现 {edge.weight} · {edge.shared_episodes.length} 话
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Outfits */}
                        {selectedNode.outfits.length > 0 && (
                            <div className="space-y-2 pb-3.5 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                                <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                    服装造型 ({selectedNode.outfits.length})
                                </div>
                                <div className="space-y-1.5">
                                    {selectedNode.outfits.map((of) => (
                                        <div
                                            key={of.id}
                                            className="rounded border p-2 flex items-center gap-2.5"
                                            style={{ backgroundColor: 'var(--bg-app)', borderColor: 'var(--border-subtle)' }}
                                        >
                                            {of.image_path && (
                                                <img
                                                    src={storageFileUrl(of.image_path)}
                                                    alt={of.name}
                                                    className="w-8 h-8 rounded-[3px] object-cover grayscale shrink-0"
                                                />
                                            )}
                                            <span className="text-xs leading-snug" style={{ color: 'var(--text-primary)' }}>
                                                {of.name}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Chronological State Evolution */}
                        <div className="space-y-2">
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                状态演变记录 ({selectedNode.state_timeline.length})
                            </div>
                            {selectedNode.state_timeline.length === 0 ? (
                                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    暂无跨话状态变更记录
                                </div>
                            ) : (
                                <div className="space-y-3 border-l pl-3 ml-1" style={{ borderColor: 'var(--border)' }}>
                                    {selectedNode.state_timeline.map((st, idx) => (
                                        <div key={idx} className="text-xs space-y-1 relative">
                                            <span
                                                className="w-1.5 h-1.5 rounded-full absolute -left-[15.5px] top-1.5"
                                                style={{ backgroundColor: 'var(--accent)' }}
                                            />
                                            <div className="font-mono text-[11px] font-semibold" style={{ color: 'var(--text-primary)' }}>
                                                Ep.{st.episode_label} · {st.attribute}
                                            </div>
                                            <div className="leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                                {st.before ? `${st.before} → ` : ''}
                                                {st.after}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ) : selectedEdge ? (
                    <div className="space-y-4">
                        <div className="pb-3 border-b space-y-1" style={{ borderColor: 'var(--border-subtle)' }}>
                            <div className="font-editorial text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                                {nodeById.get(selectedEdge.source)?.name} — {nodeById.get(selectedEdge.target)?.name}
                            </div>
                            <div className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                共现权重 {selectedEdge.weight} · 同场章节：
                                {selectedEdge.shared_episodes.map((n) => `Ep.${n}`).join(', ')}
                            </div>
                        </div>

                        <div className="space-y-2">
                            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                                交集剧情事件 ({selectedEdge.moments.length})
                            </div>
                            {selectedEdge.moments.length === 0 ? (
                                <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    双方在上述章节中同场登场。
                                </div>
                            ) : (
                                selectedEdge.moments.map((m, idx) => (
                                    <div
                                        key={idx}
                                        className="py-2 border-b space-y-1 text-xs"
                                        style={{ borderColor: 'var(--border-subtle)' }}
                                    >
                                        <div className="flex items-center justify-between font-mono text-[11px]">
                                            <span style={{ color: 'var(--accent)' }}>Ep.{m.episode_label}</span>
                                            {m.location && <span style={{ color: 'var(--text-muted)' }}>{m.location}</span>}
                                        </div>
                                        <div className="leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                                            {m.description}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                ) : (
                    <Empty description="点击图谱中的角色节点或连线查看详情" />
                )}
            </ResizableInspector>
        </div>
    )
}
