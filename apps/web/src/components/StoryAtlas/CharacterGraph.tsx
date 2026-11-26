import { useMemo, useState } from 'react'
import { Tag, Empty, Button, RadioGroup, Select, Toast } from '@douyinfe/semi-ui'
import { assetService, storageFileUrl } from '@/services/project'
import type { StoryGraphCharacterNode, StoryGraphEdge } from '@/services/project'

interface Props {
    nodes: StoryGraphCharacterNode[]
    edges: StoryGraphEdge[]
    onStatusUpdated?: () => void
}

const ROLE_STYLES: Record<string, { stroke: string; glow: string; bg: string; label: string }> = {
    protagonist: { stroke: '#ff5a36', glow: 'rgba(255,90,54,0.22)', bg: '#fff4f0', label: '主角' },
    main: { stroke: '#2563eb', glow: 'rgba(37,99,235,0.20)', bg: '#eff6ff', label: '主要角色' },
    antagonist: { stroke: '#8b5cf6', glow: 'rgba(139,92,246,0.20)', bg: '#f5f3ff', label: '反派/对手' },
    support: { stroke: '#10b981', glow: 'rgba(16,185,129,0.20)', bg: '#ecfdf5', label: '配角' },
}

const VITAL_META: Record<string, { label: string; badgeBg: string; badgeText: string }> = {
    alive: { label: '存活', badgeBg: 'bg-emerald-50/90 border-emerald-200', badgeText: 'text-emerald-700' },
    injured: { label: '重伤 / 失能', badgeBg: 'bg-amber-50/90 border-amber-200', badgeText: 'text-amber-700' },
    missing: { label: '失踪 / 下落不明', badgeBg: 'bg-violet-50/90 border-violet-200', badgeText: 'text-violet-700' },
    sealed: { label: '封印 / 囚禁', badgeBg: 'bg-sky-50/90 border-sky-200', badgeText: 'text-sky-700' },
    deceased: { label: '† 已故（死亡锁定）', badgeBg: 'bg-rose-50/90 border-rose-200', badgeText: 'text-rose-700' },
}

const SVG_W = 880
const SVG_H = 540
const CX = SVG_W / 2
const CY = SVG_H / 2

export default function CharacterGraph({ nodes, edges, onStatusUpdated }: Props) {
    const [limitMode, setLimitMode] = useState<'top' | 'all'>('top')
    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(nodes[0]?.id ?? null)
    const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null)
    const [savingStatus, setSavingStatus] = useState(false)

    const visibleNodes = useMemo(
        () => (limitMode === 'top' ? nodes.slice(0, 16) : nodes.slice(0, 40)),
        [nodes, limitMode],
    )

    const visibleIdSet = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])

    const visibleEdges = useMemo(
        () => edges.filter((e) => visibleIdSet.has(e.source) && visibleIdSet.has(e.target)).slice(0, 80),
        [edges, visibleIdSet],
    )

    // Deterministic dual-ring constellation layout with repulsion relaxation
    const positions = useMemo(() => {
        const pos = new Map<string, { x: number; y: number; r: number }>()
        const n = visibleNodes.length
        if (n === 0) return pos

        const maxApp = Math.max(...visibleNodes.map((v) => v.appearances || 1), 1)
        const innerCount = Math.min(n, Math.max(3, Math.min(6, Math.ceil(n * 0.35))))

        visibleNodes.forEach((node, idx) => {
            const ratio = (node.appearances || 1) / maxApp
            const r = Math.round(25 + ratio * 15)
            if (n === 1) {
                pos.set(node.id, { x: CX, y: CY, r: 38 })
                return
            }
            if (idx < innerCount) {
                const angle = (idx / innerCount) * Math.PI * 2 - Math.PI / 2
                const rad = innerCount <= 3 ? 122 : 138
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.18,
                    y: CY + Math.sin(angle) * rad * 0.92,
                    r,
                })
            } else {
                const outerIdx = idx - innerCount
                const outerTotal = Math.max(1, n - innerCount)
                const angle = (outerIdx / outerTotal) * Math.PI * 2 - Math.PI / 2 + 0.28
                const rad = 228
                pos.set(node.id, {
                    x: CX + Math.cos(angle) * rad * 1.38,
                    y: CY + Math.sin(angle) * rad * 0.94,
                    r,
                })
            }
        })

        const ids = visibleNodes.map((v) => v.id)
        for (let iter = 0; iter < 26; iter++) {
            for (let i = 0; i < ids.length; i++) {
                for (let j = i + 1; j < ids.length; j++) {
                    const a = pos.get(ids[i])!
                    const b = pos.get(ids[j])!
                    const dx = b.x - a.x
                    const dy = b.y - a.y
                    const dist = Math.hypot(dx, dy) || 1
                    const minDist = a.r + b.r + 44
                    if (dist < minDist) {
                        const push = (minDist - dist) * 0.25
                        const ux = dx / dist
                        const uy = dy / dist
                        a.x = Math.max(70, Math.min(SVG_W - 70, a.x - ux * push))
                        a.y = Math.max(58, Math.min(SVG_H - 86, a.y - uy * push))
                        b.x = Math.max(70, Math.min(SVG_W - 70, b.x + ux * push))
                        b.y = Math.max(58, Math.min(SVG_H - 86, b.y + uy * push))
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
                    : `已锁定 ${node.name} 状态为「${VITAL_META[nextVal]?.label || nextVal}」`,
            )
            onStatusUpdated?.()
        } catch {
            Toast.error('更新角色生命状态失败')
        } finally {
            setSavingStatus(false)
        }
    }

    if (nodes.length === 0) {
        return <Empty description="暂未提取角色节点，请先对已导入章节执行「多模态剧情理解」。" />
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h3 className="text-base font-extrabold text-slate-900 m-0 tracking-tight">人物共现与命运演进图谱</h3>
                    <p className="text-xs text-slate-500 m-0 mt-0.5">
                        节点大小映射出场话数，彩色光环区分角色定位；已故角色自动转为黑白肖像并锁定续画禁活，点击头像查看服装与状态轨迹
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="hidden md:flex items-center gap-2.5 text-[11px] font-semibold text-slate-600 bg-slate-50 px-3 py-1.5 rounded-full border border-slate-200/80">
                        {Object.entries(ROLE_STYLES).map(([k, v]) => (
                            <span key={k} className="inline-flex items-center gap-1.5">
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

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
                {/* Bright Airy Figma / Pixiv Pop Constellation Canvas */}
                <div className="xl:col-span-8 rounded-3xl border border-slate-200/90 bg-gradient-to-br from-white via-[#f7faff] to-[#fff7f5] overflow-hidden relative shadow-sm">
                    <svg
                        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
                        className="w-full h-auto block select-none"
                        style={{ minHeight: 430 }}
                    >
                        <defs>
                            <pattern id="pop-dot-grid" width="22" height="22" patternUnits="userSpaceOnUse">
                                <circle cx="2" cy="2" r="1" fill="#cbd5e1" fillOpacity="0.45" />
                            </pattern>
                            <radialGradient id="pop-center-aura" cx="50%" cy="50%" r="55%">
                                <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.11" />
                                <stop offset="55%" stopColor="#ff5a36" stopOpacity="0.06" />
                                <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
                            </radialGradient>
                            <filter id="deceased-mono">
                                <feColorMatrix type="saturate" values="0" />
                            </filter>
                            <filter id="pill-shadow" x="-20%" y="-20%" width="140%" height="160%">
                                <feDropShadow dx="0" dy="2" stdDeviation="2.5" floodColor="#0f172a" floodOpacity="0.1" />
                            </filter>
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

                        {/* Crisp Bright Dot Canvas + Soft Orbital Rings */}
                        <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="url(#pop-dot-grid)" />
                        <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="url(#pop-center-aura)" />
                        <ellipse cx={CX} cy={CY} rx={155} ry={125} fill="none" stroke="#dbeafe" strokeWidth={1.5} strokeDasharray="5 7" />
                        <ellipse cx={CX} cy={CY} rx={305} ry={210} fill="none" stroke="#e2e8f0" strokeWidth={1.2} strokeDasharray="4 8" />

                        {/* Co-occurrence Edges */}
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
                                    <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={14} />
                                    <line
                                        x1={a.x}
                                        y1={a.y}
                                        x2={b.x}
                                        y2={b.y}
                                        stroke={isSelected ? '#ff5a36' : isHighlighted ? '#2563eb' : '#94a3b8'}
                                        strokeWidth={isSelected ? strokeWidth + 1.4 : strokeWidth}
                                        strokeOpacity={dimmed ? 0.14 : isHighlighted ? 0.85 : 0.34}
                                        strokeLinecap="round"
                                    />
                                    {(isHighlighted || edge.weight >= Math.max(3, Math.ceil(maxWeight * 0.65))) && (
                                        <g opacity={dimmed ? 0.15 : 1} filter="url(#pill-shadow)">
                                            <circle cx={mx} cy={my} r={11} fill="#ffffff" stroke={isSelected ? '#ff5a36' : '#3b82f6'} strokeWidth={1.6} />
                                            <text
                                                x={mx}
                                                y={my + 3.5}
                                                textAnchor="middle"
                                                fontSize={9.5}
                                                fontWeight={800}
                                                fill={isSelected ? '#ff5a36' : '#2563eb'}
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
                            const roleStyle = ROLE_STYLES[node.role] || ROLE_STYLES.support
                            const isDeceased = node.vital_status === 'deceased'
                            const isUnavailable = node.vital_status === 'missing' || node.vital_status === 'sealed'
                            const ringColor = isDeceased ? '#94a3b8' : roleStyle.stroke
                            const isSelected = selectedNodeId === node.id
                            const dimmed = connectedToHover !== null && !connectedToHover.has(node.id)
                            const initials = node.name.slice(0, 2)
                            const labelText = node.name.length > 7 ? `${node.name.slice(0, 6)}…` : node.name
                            const pillW = Math.min(130, Math.max(64, labelText.length * 14 + 26))

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
                                    {/* Soft pastel aura */}
                                    <circle
                                        cx={p.x}
                                        cy={p.y}
                                        r={p.r + (isSelected ? 11 : 6)}
                                        fill={isDeceased ? 'rgba(148,163,184,0.16)' : roleStyle.glow}
                                    />
                                    {isSelected && (
                                        <circle
                                            cx={p.x}
                                            cy={p.y}
                                            r={p.r + 6.5}
                                            fill="none"
                                            stroke={ringColor}
                                            strokeWidth={2.2}
                                            strokeDasharray="5 3"
                                        />
                                    )}
                                    <circle
                                        cx={p.x}
                                        cy={p.y}
                                        r={p.r}
                                        fill={isDeceased ? '#f1f5f9' : roleStyle.bg}
                                        stroke={ringColor}
                                        strokeWidth={isSelected ? 3.2 : 2.5}
                                        strokeDasharray={isUnavailable ? '4 3' : undefined}
                                        filter="url(#pill-shadow)"
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
                                            filter={isDeceased ? 'url(#deceased-mono)' : undefined}
                                            opacity={isDeceased ? 0.72 : 1}
                                        />
                                    ) : (
                                        <text
                                            x={p.x}
                                            y={p.y + 5}
                                            textAnchor="middle"
                                            fontSize={13}
                                            fontWeight={800}
                                            fill={ringColor}
                                        >
                                            {initials}
                                        </text>
                                    )}

                                    {/* Top-right pill badge: † if deceased, else appearance count */}
                                    <circle
                                        cx={p.x + p.r * 0.72}
                                        cy={p.y - p.r * 0.72}
                                        r={11}
                                        fill={isDeceased ? '#f43f5e' : ringColor}
                                        stroke="#ffffff"
                                        strokeWidth={2}
                                    />
                                    <text
                                        x={p.x + p.r * 0.72}
                                        y={p.y - p.r * 0.72 + (isDeceased ? 4.2 : 3.5)}
                                        textAnchor="middle"
                                        fontSize={isDeceased ? 12.5 : 9.5}
                                        fontWeight={800}
                                        fill="#ffffff"
                                    >
                                        {isDeceased ? '†' : node.appearances}
                                    </text>

                                    {/* Crisp Floating White Nameplate Pill */}
                                    <g filter="url(#pill-shadow)">
                                        <rect
                                            x={p.x - pillW / 2}
                                            y={p.y + p.r + 7}
                                            width={pillW}
                                            height={23}
                                            rx={11.5}
                                            fill="#ffffff"
                                            stroke={isSelected ? ringColor : '#e2e8f0'}
                                            strokeWidth={isSelected ? 1.8 : 1.1}
                                        />
                                        <text
                                            x={p.x}
                                            y={p.y + p.r + 22}
                                            textAnchor="middle"
                                            fontSize={11.5}
                                            fontWeight={700}
                                            fill={isDeceased ? '#64748b' : '#0f172a'}
                                        >
                                            {labelText}
                                        </text>
                                    </g>
                                </g>
                            )
                        })}
                    </svg>
                </div>

                {/* Right-side Crisp Apple / Pixiv Style Character Dossier */}
                <div className="xl:col-span-4 rounded-3xl border border-slate-200/90 bg-white p-5 space-y-4 max-h-[540px] overflow-y-auto shadow-sm">
                    {selectedNode ? (
                        (() => {
                            const vKey = selectedNode.vital_status || 'alive'
                            const vMeta = VITAL_META[vKey] || VITAL_META.alive
                            const isDeceased = vKey === 'deceased'
                            return (
                                <>
                                    <div className="flex items-start gap-3.5 pb-3.5 border-b border-slate-100">
                                        {selectedNode.avatar_path ? (
                                            <img
                                                src={storageFileUrl(selectedNode.avatar_path)}
                                                alt={selectedNode.name}
                                                className={`w-16 h-16 rounded-2xl object-cover border-2 border-slate-100 shadow-sm shrink-0 ${
                                                    isDeceased ? 'grayscale opacity-75' : ''
                                                }`}
                                            />
                                        ) : (
                                            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-sky-400 text-white font-bold text-lg flex items-center justify-center shrink-0">
                                                {selectedNode.name.slice(0, 2)}
                                            </div>
                                        )}
                                        <div className="min-w-0 flex-1 space-y-1.5">
                                            <div className="flex items-center gap-1.5 flex-wrap">
                                                <span className="font-black text-base text-slate-900">
                                                    {selectedNode.name}
                                                </span>
                                                <Tag size="small" color="orange">
                                                    {(ROLE_STYLES[selectedNode.role] || ROLE_STYLES.support).label}
                                                </Tag>
                                                <Tag size="small" color="blue">
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

                                    {/* Iterative Vital Status + Author Manual Override */}
                                    <div className={`rounded-2xl border p-3.5 space-y-2 ${vMeta.badgeBg}`}>
                                        <div className="flex items-center justify-between gap-2">
                                            <span className={`text-xs font-extrabold ${vMeta.badgeText}`}>
                                                生命状态：{vMeta.label}
                                                {selectedNode.vital_status_episode ? `（第 ${selectedNode.vital_status_episode} 话）` : ''}
                                            </span>
                                            {selectedNode.vital_status_override && (
                                                <Tag size="small" color="red">
                                                    手动锁定
                                                </Tag>
                                            )}
                                        </div>
                                        {selectedNode.vital_status_note && (
                                            <div className="text-[11px] text-slate-600 leading-snug">
                                                {selectedNode.vital_status_note}
                                            </div>
                                        )}
                                        <div className="flex items-center gap-2 pt-0.5">
                                            <span className="text-[11px] font-semibold text-slate-500 shrink-0">作者覆写：</span>
                                            <Select
                                                size="small"
                                                loading={savingStatus}
                                                style={{ flex: 1 }}
                                                value={selectedNode.vital_status_override || 'auto'}
                                                onChange={(val) => handleOverrideStatus(selectedNode, String(val || 'auto'))}
                                            >
                                                <Select.Option value="auto">跟随剧情自动迭代</Select.Option>
                                                <Select.Option value="alive">强制锁定：存活</Select.Option>
                                                <Select.Option value="injured">强制锁定：重伤/失能</Select.Option>
                                                <Select.Option value="missing">强制锁定：失踪</Select.Option>
                                                <Select.Option value="sealed">强制锁定：封印</Select.Option>
                                                <Select.Option value="deceased">强制锁定：† 已故（续画禁活）</Select.Option>
                                            </Select>
                                        </div>
                                    </div>

                                    {selectedNode.description && (
                                        <div className="text-xs text-slate-700 leading-relaxed bg-slate-50/80 rounded-2xl p-3.5 border border-slate-100">
                                            {selectedNode.description}
                                        </div>
                                    )}

                                    {selectedNode.speech_style && (
                                        <div className="space-y-1">
                                            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                                                台词口癖与性格
                                            </div>
                                            <div className="text-xs text-blue-900 bg-blue-50/70 rounded-xl px-3 py-2 border border-blue-100">
                                                {selectedNode.speech_style}
                                            </div>
                                        </div>
                                    )}

                                    {selectedNode.outfits.length > 0 && (
                                        <div className="space-y-1.5">
                                            <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                                                服装造型 ({selectedNode.outfits.length})
                                            </div>
                                            <div className="grid grid-cols-2 gap-2">
                                                {selectedNode.outfits.slice(0, 4).map((of) => (
                                                    <div key={of.id} className="rounded-xl border border-slate-200/80 p-2 bg-slate-50/60 flex items-center gap-2 hover:border-blue-300 transition">
                                                        {of.image_path && (
                                                            <img
                                                                src={storageFileUrl(of.image_path)}
                                                                alt={of.name}
                                                                className="w-9 h-9 rounded-lg object-cover shrink-0"
                                                            />
                                                        )}
                                                        <div className="min-w-0">
                                                            <div className="text-xs font-bold text-slate-800 truncate">{of.name}</div>
                                                            {of.description && (
                                                                <div className="text-[10px] text-slate-500 line-clamp-1">{of.description}</div>
                                                            )}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    <div className="space-y-2">
                                        <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                                            跨话状态演进 ({selectedNode.state_timeline.length})
                                        </div>
                                        {selectedNode.state_timeline.length === 0 ? (
                                            <div className="text-xs text-slate-400">暂无跨话状态变更记录</div>
                                        ) : (
                                            <div className="space-y-2 border-l-2 border-blue-200 pl-3 ml-1">
                                                {selectedNode.state_timeline.map((st, idx) => (
                                                    <div key={idx} className="text-xs space-y-0.5 relative">
                                                        <span className="w-2.5 h-2.5 rounded-full bg-[#ff5a36] border-2 border-white shadow absolute -left-[18px] top-1" />
                                                        <div className="font-bold text-slate-800">
                                                            第 {st.episode_label} 话 · {st.attribute}
                                                        </div>
                                                        <div className="text-slate-600">
                                                            {st.before ? `${st.before} → ` : ''}
                                                            <span className="text-emerald-700 font-semibold">{st.after}</span>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </>
                            )
                        })()
                    ) : selectedEdge ? (
                        <div className="space-y-4">
                            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                                <div className="font-bold text-sm text-slate-900">
                                    {nodeById.get(selectedEdge.source)?.name || '角色A'} ↔{' '}
                                    {nodeById.get(selectedEdge.target)?.name || '角色B'}
                                </div>
                                <Tag color="blue">共现权重 {selectedEdge.weight}</Tag>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {selectedEdge.shared_episodes.map((epNo) => (
                                    <Tag key={epNo} size="small" color="cyan">
                                        第 {epNo} 话同场
                                    </Tag>
                                ))}
                            </div>
                            <div className="space-y-2">
                                <div className="text-[11px] font-bold text-slate-400 uppercase">
                                    关键交集事件 ({selectedEdge.moments.length})
                                </div>
                                {selectedEdge.moments.length === 0 ? (
                                    <div className="text-xs text-slate-500">双方在以上章节中同场出场。</div>
                                ) : (
                                    selectedEdge.moments.map((m, idx) => (
                                        <div key={idx} className="rounded-2xl bg-slate-50 border border-slate-200/80 p-3 space-y-1 text-xs">
                                            <div className="flex items-center justify-between">
                                                <span className="font-bold text-blue-600">第 {m.episode_label} 话</span>
                                                {m.location && <span className="text-slate-400">{m.location}</span>}
                                            </div>
                                            <div className="text-slate-700 leading-relaxed">{m.description}</div>
                                        </div>
                                    ))
                                )}
                            </div>
                            <Button
                                size="small"
                                theme="light"
                                onClick={() => {
                                    setSelectedEdgeKey(null)
                                    setSelectedNodeId(selectedEdge.source)
                                }}
                            >
                                查看 {nodeById.get(selectedEdge.source)?.name} 档案
                            </Button>
                        </div>
                    ) : (
                        <Empty description="点击图谱中的任意角色头像或连线查看详情" />
                    )}
                </div>
            </div>
        </div>
    )
}
