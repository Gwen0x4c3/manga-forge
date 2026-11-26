import { useState, useRef, useEffect, useCallback } from 'react'
import { Button, Input, TextArea, Select, Slider, Toast } from '@douyinfe/semi-ui'
import { storageFileUrl } from '@/services/project'
import type { BubbleCustomBox, BubbleLayoutItem, ComposedPage, GenerationRun, Storyboard } from '@/services/project'
import ResizableInspector from './ResizableInspector'
import {
    IconZoomIn,
    IconZoomOut,
    IconFit,
    IconSliders,
    IconLayers,
    IconHistory,
    IconDownload,
    IconSidebarToggle,
} from './StudioIcons'

interface Props {
    episodeId: string
    pages: ComposedPage[]
    storyboard: Storyboard | null
    runs?: GenerationRun[]
    writingMode: 'horizontal' | 'vertical'
    onWritingModeChange: (mode: 'horizontal' | 'vertical') => void
    onApplyAndRecompose: (nextStoryboard: Storyboard, mode: 'horizontal' | 'vertical') => Promise<void>
    recomposing: boolean
}

const BUBBLE_STYLES = [
    { value: 'speech', label: '标准对白' },
    { value: 'shout', label: '呐喊尖刺' },
    { value: 'thought', label: '心声云朵' },
    { value: 'whisper', label: '低语虚线' },
    { value: 'narration', label: '旁白方框' },
    { value: 'sfx', label: '拟声特效' },
]

const TAIL_OPTIONS = [
    { value: 'center', label: '自动朝向' },
    { value: 'top-left', label: '左上' },
    { value: 'top-right', label: '右上' },
    { value: 'bottom-left', label: '左下' },
    { value: 'bottom-right', label: '右下' },
    { value: 'left', label: '偏左' },
    { value: 'right', label: '偏右' },
]

type InspectorTab = 'props' | 'layers' | 'history'

export default function BubbleCanvasEditor({
    episodeId,
    pages,
    storyboard,
    runs = [],
    writingMode,
    onWritingModeChange,
    onApplyAndRecompose,
    recomposing,
}: Props) {
    const [activePageNo, setActivePageNo] = useState<number>(pages[0]?.page_number || 1)
    const [thumbRailOpen, setThumbRailOpen] = useState(true)
    const [showOverlay, setShowOverlay] = useState(true)
    const [inspectorTab, setInspectorTab] = useState<InspectorTab>('props')
    const [selectedKey, setSelectedKey] = useState<string | null>(null)
    const [zoom, setZoom] = useState<number>(0.88)
    const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
    const [spaceDown, setSpaceDown] = useState(false)

    const [localStoryboard, setLocalStoryboard] = useState<Storyboard | null>(() =>
        storyboard ? structuredClone(storyboard) : null,
    )
    const [dragOverrides, setDragOverrides] = useState<Record<string, { pageX: number; pageY: number }>>({})

    const sheetRef = useRef<HTMLDivElement | null>(null)
    const panDragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
    const bubbleDragRef = useRef<{
        key: string
        bubble: BubbleLayoutItem
        startClientX: number
        startClientY: number
        origPageX: number
        origPageY: number
    } | null>(null)

    useEffect(() => {
        if (storyboard) {
            setLocalStoryboard(structuredClone(storyboard))
            setDragOverrides({})
        }
    }, [storyboard])

    useEffect(() => {
        if (pages.length > 0 && !pages.some((p) => p.page_number === activePageNo)) {
            setActivePageNo(pages[0].page_number)
        }
    }, [pages, activePageNo])

    const handleSyncRecompose = useCallback(async () => {
        if (!localStoryboard) {
            Toast.warning('未找到对应分镜数据')
            return
        }
        await onApplyAndRecompose(localStoryboard, writingMode)
    }, [localStoryboard, onApplyAndRecompose, writingMode])

    // Keyboard shortcuts: +/- zoom, 0 fit, H toggle overlay, Space pan, Cmd/Ctrl+Enter sync
    useEffect(() => {
        const isTypingTarget = (el: EventTarget | null) => {
            if (!(el instanceof HTMLElement)) return false
            const tag = el.tagName.toLowerCase()
            return tag === 'input' || tag === 'textarea' || el.isContentEditable
        }
        const onKeyDown = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault()
                handleSyncRecompose()
                return
            }
            if (isTypingTarget(e.target)) return
            if (e.code === 'Space') {
                e.preventDefault()
                setSpaceDown(true)
            } else if (e.key === '=' || e.key === '+') {
                e.preventDefault()
                setZoom((z) => Math.min(2.2, Number((z + 0.15).toFixed(2))))
            } else if (e.key === '-') {
                e.preventDefault()
                setZoom((z) => Math.max(0.4, Number((z - 0.15).toFixed(2))))
            } else if (e.key === '0') {
                e.preventDefault()
                setZoom(0.88)
                setPan({ x: 0, y: 0 })
            } else if (e.key.toLowerCase() === 'h') {
                setShowOverlay((v) => !v)
            }
        }
        const onKeyUp = (e: KeyboardEvent) => {
            if (e.code === 'Space') setSpaceDown(false)
        }
        window.addEventListener('keydown', onKeyDown)
        window.addEventListener('keyup', onKeyUp)
        return () => {
            window.removeEventListener('keydown', onKeyDown)
            window.removeEventListener('keyup', onKeyUp)
        }
    }, [handleSyncRecompose])

    const currentPage = pages.find((p) => p.page_number === activePageNo) || pages[0]
    if (!currentPage) return null

    const panelBoxes = currentPage.panel_boxes || []
    const bubbleLayouts = currentPage.bubble_layouts || []
    const panelBoxById = new Map(panelBoxes.map((pb) => [pb.panel_id, pb]))

    const bubbleKey = (b: BubbleLayoutItem) => `${b.panel_id}::${b.dialogue_index}`
    const selectedBubble = bubbleLayouts.find((b) => bubbleKey(b) === selectedKey) || bubbleLayouts[0] || null

    const locateDialogueInDraft = (sb: Storyboard | null, panelId: string, dialogueIndex: number) => {
        if (!sb) return null
        for (let pIdx = 0; pIdx < sb.pages.length; pIdx++) {
            const page = sb.pages[pIdx]
            for (let panIdx = 0; panIdx < page.panels.length; panIdx++) {
                const panel = page.panels[panIdx]
                if (panel.panel_id === panelId && panel.dialogue[dialogueIndex]) {
                    return { pIdx, panIdx, dIdx: dialogueIndex, dialogue: panel.dialogue[dialogueIndex] }
                }
            }
        }
        return null
    }

    const updateDialogueField = (
        panelId: string,
        dialogueIndex: number,
        updater: (dlg: Storyboard['pages'][number]['panels'][number]['dialogue'][number]) => void,
    ) => {
        if (!localStoryboard) return
        const next = structuredClone(localStoryboard)
        const loc = locateDialogueInDraft(next, panelId, dialogueIndex)
        if (!loc) return
        updater(loc.dialogue)
        setLocalStoryboard(next)
    }

    // Canvas pan & wheel zoom
    const onCanvasWheel = (e: React.WheelEvent) => {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault()
            const delta = e.deltaY < 0 ? 0.1 : -0.1
            setZoom((z) => Math.max(0.4, Math.min(2.2, Number((z + delta).toFixed(2)))))
        }
    }

    const onCanvasPointerDown = (e: React.PointerEvent) => {
        if (spaceDown || e.button === 1 || e.target === e.currentTarget) {
            panDragRef.current = { startX: e.clientX, startY: e.clientY, origX: pan.x, origY: pan.y }
            ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
        }
    }

    const onCanvasPointerMove = (e: React.PointerEvent) => {
        if (!panDragRef.current) return
        setPan({
            x: panDragRef.current.origX + (e.clientX - panDragRef.current.startX),
            y: panDragRef.current.origY + (e.clientY - panDragRef.current.startY),
        })
    }

    const onCanvasPointerUp = () => {
        panDragRef.current = null
    }

    // Bubble drag inside paper sheet
    const handleBubbleDown = (e: React.PointerEvent, bubble: BubbleLayoutItem) => {
        if (spaceDown) return
        e.stopPropagation()
        const key = bubbleKey(bubble)
        setSelectedKey(key)
        setInspectorTab('props')
        const currentPos = dragOverrides[key] || { pageX: bubble.page_x_pct, pageY: bubble.page_y_pct }
        bubbleDragRef.current = {
            key,
            bubble,
            startClientX: e.clientX,
            startClientY: e.clientY,
            origPageX: currentPos.pageX,
            origPageY: currentPos.pageY,
        }
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    }

    const handleBubbleMove = (e: React.PointerEvent) => {
        const st = bubbleDragRef.current
        const rect = sheetRef.current?.getBoundingClientRect()
        if (!st || !rect || rect.width === 0 || rect.height === 0) return

        const dxPct = (e.clientX - st.startClientX) / rect.width
        const dyPct = (e.clientY - st.startClientY) / rect.height
        const pb = panelBoxById.get(st.bubble.panel_id)

        let nextPageX = st.origPageX + dxPct
        let nextPageY = st.origPageY + dyPct

        if (pb) {
            nextPageX = Math.max(pb.x_pct, Math.min(pb.x_pct + pb.w_pct - st.bubble.page_w_pct, nextPageX))
            nextPageY = Math.max(pb.y_pct, Math.min(pb.y_pct + pb.h_pct - st.bubble.page_h_pct, nextPageY))
        } else {
            nextPageX = Math.max(0.01, Math.min(0.95 - st.bubble.page_w_pct, nextPageX))
            nextPageY = Math.max(0.01, Math.min(0.95 - st.bubble.page_h_pct, nextPageY))
        }
        setDragOverrides((prev) => ({ ...prev, [st.key]: { pageX: nextPageX, pageY: nextPageY } }))
    }

    const handleBubbleUp = () => {
        const st = bubbleDragRef.current
        if (!st) return
        bubbleDragRef.current = null
        const pos = dragOverrides[st.key]
        const pb = panelBoxById.get(st.bubble.panel_id)
        if (!pos || !pb || pb.w_pct <= 0 || pb.h_pct <= 0) return

        const relX = Math.max(0, Math.min(0.95, (pos.pageX - pb.x_pct) / pb.w_pct))
        const relY = Math.max(0, Math.min(0.95, (pos.pageY - pb.y_pct) / pb.h_pct))

        updateDialogueField(st.bubble.panel_id, st.bubble.dialogue_index, (dlg) => {
            const prevBox: BubbleCustomBox = dlg.custom_box || {}
            dlg.custom_box = {
                ...prevBox,
                x_pct: Number(relX.toFixed(4)),
                y_pct: Number(relY.toFixed(4)),
            }
        })
    }

    const selectedDraftLoc = selectedBubble
        ? locateDialogueInDraft(localStoryboard, selectedBubble.panel_id, selectedBubble.dialogue_index)
        : null

    return (
        <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* LEFT RAIL: Collapsible Page Thumbnails */}
            {thumbRailOpen ? (
                <aside
                    className="w-40 shrink-0 border-r flex flex-col min-h-0 select-none"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <div
                        className="h-10 px-3 border-b flex items-center justify-between shrink-0"
                        style={{ borderColor: 'var(--border)' }}
                    >
                        <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-secondary)' }}>
                            页面 ({pages.length})
                        </span>
                        <button
                            type="button"
                            title="折叠页面栏"
                            onClick={() => setThumbRailOpen(false)}
                            className="w-6 h-6 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            <IconSidebarToggle size={13} />
                        </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-2.5 space-y-3">
                        {pages.map((p) => {
                            const active = p.page_number === currentPage.page_number
                            return (
                                <button
                                    key={p.page_number}
                                    type="button"
                                    onClick={() => {
                                        setActivePageNo(p.page_number)
                                        setSelectedKey(null)
                                        setPan({ x: 0, y: 0 })
                                    }}
                                    className="w-full text-left bg-transparent border-0 p-0 cursor-pointer group"
                                >
                                    <div
                                        className="rounded overflow-hidden border-2 transition-colors"
                                        style={{
                                            backgroundColor: 'var(--paper)',
                                            borderColor: active ? 'var(--accent)' : 'var(--border)',
                                        }}
                                    >
                                        <img
                                            src={storageFileUrl(p.image_path)}
                                            alt={`P${p.page_number}`}
                                            className="w-full aspect-[210/297] object-cover block"
                                        />
                                    </div>
                                    <div className="mt-1 flex items-center justify-between px-0.5 text-[11px]">
                                        <span
                                            className="font-mono font-medium"
                                            style={{ color: active ? 'var(--text-primary)' : 'var(--text-secondary)' }}
                                        >
                                            P{String(p.page_number).padStart(2, '0')}
                                        </span>
                                        <span className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>
                                            {p.layout}
                                        </span>
                                    </div>
                                </button>
                            )
                        })}
                    </div>
                </aside>
            ) : (
                <div
                    className="w-9 shrink-0 border-r flex flex-col items-center py-2.5 gap-2"
                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
                >
                    <button
                        type="button"
                        title="展开页面缩略图"
                        onClick={() => setThumbRailOpen(true)}
                        className="w-6 h-6 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconSidebarToggle size={14} />
                    </button>
                </div>
            )}

            {/* CENTER INFINITE CANVAS (#303034 dark studio desk + archival #F5F3EF paper sheet) */}
            <div
                onWheel={onCanvasWheel}
                onPointerDown={onCanvasPointerDown}
                onPointerMove={onCanvasPointerMove}
                onPointerUp={onCanvasPointerUp}
                className={`flex-1 min-w-0 min-h-0 relative overflow-hidden mf-canvas-grid flex items-center justify-center select-none ${
                    spaceDown ? 'cursor-grab active:cursor-grabbing' : 'cursor-default'
                }`}
            >
                {/* Top-left subtle manuscript metadata stamp */}
                <div
                    className="absolute top-3 left-3.5 z-10 flex items-center gap-2 text-[11px] font-mono px-2.5 py-1 rounded border"
                    style={{
                        backgroundColor: 'var(--bg-panel)',
                        borderColor: 'var(--border)',
                        color: 'var(--text-secondary)',
                    }}
                >
                    <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                        PAGE {String(currentPage.page_number).padStart(2, '0')}
                    </span>
                    <span style={{ color: 'var(--border)' }}>|</span>
                    <span>{currentPage.layout}</span>
                    <span style={{ color: 'var(--border)' }}>|</span>
                    <span>{writingMode === 'vertical' ? '竖排日漫' : '横排'}</span>
                    <span style={{ color: 'var(--border)' }}>|</span>
                    <span>2480 × 3508</span>
                </div>

                {/* Archival Paper Manuscript Sheet */}
                <div
                    style={{
                        transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                        transformOrigin: 'center center',
                        transition: panDragRef.current ? 'none' : 'transform 0.08s ease-out',
                    }}
                >
                    <div
                        ref={sheetRef}
                        className="relative mf-paper-sheet overflow-hidden"
                        style={{ width: 540 }}
                    >
                        <img
                            src={storageFileUrl(currentPage.image_path)}
                            alt={`Composed Page ${currentPage.page_number}`}
                            className="w-full block pointer-events-none"
                        />

                        {showOverlay && (
                            <div className="absolute inset-0">
                                {panelBoxes.map((pb) => (
                                    <div
                                        key={pb.panel_id}
                                        className="absolute border border-black/15 pointer-events-none"
                                        style={{
                                            left: `${pb.x_pct * 100}%`,
                                            top: `${pb.y_pct * 100}%`,
                                            width: `${pb.w_pct * 100}%`,
                                            height: `${pb.h_pct * 100}%`,
                                        }}
                                    >
                                        <span className="absolute bottom-1 right-1 bg-[#18181B]/75 text-[#F4F4F5] text-[9px] font-mono px-1 py-0.5 rounded-[2px]">
                                            {pb.panel_id}
                                        </span>
                                    </div>
                                ))}

                                {bubbleLayouts.map((b) => {
                                    const key = bubbleKey(b)
                                    const isSel = selectedBubble ? bubbleKey(selectedBubble) === key : false
                                    const pos = dragOverrides[key] || { pageX: b.page_x_pct, pageY: b.page_y_pct }
                                    return (
                                        <div
                                            key={key}
                                            onPointerDown={(e) => handleBubbleDown(e, b)}
                                            onPointerMove={handleBubbleMove}
                                            onPointerUp={handleBubbleUp}
                                            title="拖动调整气泡坐标"
                                            className={`absolute rounded-[3px] cursor-grab active:cursor-grabbing ${
                                                isSel
                                                    ? 'border-[1.5px] border-[#E64B35] bg-[#E64B35]/10'
                                                    : 'border border-dashed border-[#18181B]/45 hover:border-[#E64B35]/80 hover:bg-[#E64B35]/5'
                                            }`}
                                            style={{
                                                left: `${pos.pageX * 100}%`,
                                                top: `${pos.pageY * 100}%`,
                                                width: `${Math.max(5, b.page_w_pct * 100)}%`,
                                                height: `${Math.max(4, b.page_h_pct * 100)}%`,
                                            }}
                                        >
                                            {isSel && (
                                                <span className="absolute -top-4 left-0 text-[9px] font-mono px-1 py-[1px] rounded-[2px] bg-[#E64B35] text-white whitespace-nowrap pointer-events-none">
                                                    {b.panel_id}#{b.dialogue_index + 1} · {b.speaker || '对白'}
                                                </span>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                </div>

                {/* FLOATING CANVAS TOOLBAR (Bottom Center) */}
                <div
                    className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1 px-2.5 py-1.5 rounded-md border whitespace-nowrap max-w-[calc(100%-24px)] overflow-x-auto"
                    style={{
                        backgroundColor: 'var(--bg-panel)',
                        borderColor: 'var(--border)',
                        boxShadow: '0 4px 16px rgba(0,0,0,0.28)',
                    }}
                >
                    <button
                        type="button"
                        title="缩小 (-)"
                        onClick={() => setZoom((z) => Math.max(0.4, Number((z - 0.15).toFixed(2))))}
                        className="w-7 h-7 shrink-0 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconZoomOut size={14} />
                    </button>
                    <span
                        className="w-11 shrink-0 text-center text-[11px] font-mono"
                        style={{ color: 'var(--text-primary)' }}
                    >
                        {Math.round(zoom * 100)}%
                    </span>
                    <button
                        type="button"
                        title="放大 (+)"
                        onClick={() => setZoom((z) => Math.min(2.2, Number((z + 0.15).toFixed(2))))}
                        className="w-7 h-7 shrink-0 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconZoomIn size={14} />
                    </button>
                    <button
                        type="button"
                        title="适应画布 (0)"
                        onClick={() => {
                            setZoom(0.88)
                            setPan({ x: 0, y: 0 })
                        }}
                        className="w-7 h-7 shrink-0 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconFit size={14} />
                    </button>

                    <span className="h-4 w-px mx-1 shrink-0" style={{ backgroundColor: 'var(--border)' }} />

                    {/* Writing Mode Switch */}
                    <div
                        className="flex shrink-0 rounded border p-0.5 whitespace-nowrap"
                        style={{ backgroundColor: 'var(--bg-app)', borderColor: 'var(--border)' }}
                    >
                        {(['vertical', 'horizontal'] as const).map((m) => {
                            const active = writingMode === m
                            return (
                                <button
                                    key={m}
                                    type="button"
                                    onClick={() => onWritingModeChange(m)}
                                    className="px-2 py-0.5 text-[11px] rounded-[3px] border-0 cursor-pointer transition-colors whitespace-nowrap shrink-0"
                                    style={{
                                        backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                                        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                        fontWeight: active ? 600 : 400,
                                    }}
                                >
                                    {m === 'vertical' ? '竖排' : '横排'}
                                </button>
                            )
                        })}
                    </div>

                    <button
                        type="button"
                        title="显示/隐藏气泡热区 (H)"
                        onClick={() => setShowOverlay((v) => !v)}
                        className="h-7 px-2 shrink-0 rounded border text-[11px] cursor-pointer transition-colors whitespace-nowrap"
                        style={{
                            backgroundColor: showOverlay ? 'var(--bg-elevated)' : 'transparent',
                            borderColor: showOverlay ? 'var(--border)' : 'transparent',
                            color: showOverlay ? 'var(--text-primary)' : 'var(--text-secondary)',
                        }}
                    >
                        热区 (H)
                    </button>

                    <span className="h-4 w-px mx-1 shrink-0" style={{ backgroundColor: 'var(--border)' }} />

                    <Button
                        size="small"
                        theme="solid"
                        className="shrink-0 whitespace-nowrap"
                        loading={recomposing}
                        onClick={handleSyncRecompose}
                    >
                        应用重排 (⌘↵)
                    </Button>

                    <span className="h-4 w-px mx-1 shrink-0" style={{ backgroundColor: 'var(--border)' }} />

                    {(['pdf', 'cbz', 'webtoon'] as const).map((fmt) => (
                        <button
                            key={fmt}
                            type="button"
                            onClick={() =>
                                window.open(`/api/v1/generation/episodes/${episodeId}/export?format=${fmt}`, '_blank')
                            }
                            className="h-7 px-2 shrink-0 rounded border-0 bg-transparent hover:bg-[var(--bg-hover)] text-[11px] font-mono uppercase cursor-pointer flex items-center gap-1 whitespace-nowrap"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            <IconDownload size={12} />
                            {fmt === 'webtoon' ? '条漫' : fmt}
                        </button>
                    ))}
                </div>
            </div>

            {/* RIGHT COLLAPSIBLE RESIZABLE INSPECTOR (Properties / Layers / History) */}
            <ResizableInspector
                title="编辑属性"
                subtitle={`${bubbleLayouts.length} 气泡`}
            >
                <div className="space-y-4">
                    {/* Compact 3-tab Switch */}
                    <div
                        className="grid grid-cols-3 rounded border p-0.5"
                        style={{ backgroundColor: 'var(--bg-app)', borderColor: 'var(--border)' }}
                    >
                        {[
                            { key: 'props' as const, label: '属性', icon: IconSliders },
                            { key: 'layers' as const, label: '图层', icon: IconLayers },
                            { key: 'history' as const, label: '历史', icon: IconHistory },
                        ].map((t) => {
                            const Icon = t.icon
                            const active = inspectorTab === t.key
                            return (
                                <button
                                    key={t.key}
                                    type="button"
                                    onClick={() => setInspectorTab(t.key)}
                                    className="h-7 rounded-[3px] border-0 flex items-center justify-center gap-1.5 text-[11px] cursor-pointer transition-colors"
                                    style={{
                                        backgroundColor: active ? 'var(--bg-elevated)' : 'transparent',
                                        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                        fontWeight: active ? 600 : 400,
                                    }}
                                >
                                    <Icon size={12} />
                                    {t.label}
                                </button>
                            )
                        })}
                    </div>

                    {inspectorTab === 'props' && (
                        <>
                            {bubbleLayouts.length === 0 ? (
                                <div className="text-xs py-6 text-center" style={{ color: 'var(--text-muted)' }}>
                                    当前页暂无气泡图层，点击底部「应用重排」生成可交互气泡。
                                </div>
                            ) : selectedBubble && selectedDraftLoc ? (
                                <div className="space-y-3.5 text-xs">
                                    <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--border-subtle)' }}>
                                        <span className="font-mono text-[11px] font-semibold" style={{ color: 'var(--accent)' }}>
                                            PANEL {selectedBubble.panel_id} · BUBBLE #{selectedBubble.dialogue_index + 1}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                const k = bubbleKey(selectedBubble)
                                                setDragOverrides((prev) => {
                                                    const copy = { ...prev }
                                                    delete copy[k]
                                                    return copy
                                                })
                                                updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                    if (dlg.custom_box) {
                                                        delete dlg.custom_box.x_pct
                                                        delete dlg.custom_box.y_pct
                                                    }
                                                })
                                            }}
                                            className="text-[11px] bg-transparent border-0 cursor-pointer hover:underline"
                                            style={{ color: 'var(--text-secondary)' }}
                                        >
                                            重置坐标
                                        </button>
                                    </div>

                                    <div className="space-y-1">
                                        <label className="block text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                            说话人
                                        </label>
                                        <Input
                                            size="small"
                                            value={selectedDraftLoc.dialogue.speaker}
                                            onChange={(val) =>
                                                updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                    dlg.speaker = val
                                                })
                                            }
                                        />
                                    </div>

                                    <div className="space-y-1">
                                        <label className="block text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                            台词文案
                                        </label>
                                        <TextArea
                                            rows={3}
                                            value={selectedDraftLoc.dialogue.text}
                                            onChange={(val) =>
                                                updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                    dlg.text = val
                                                })
                                            }
                                        />
                                    </div>

                                    <div className="grid grid-cols-2 gap-2.5">
                                        <div className="space-y-1">
                                            <label className="block text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                                气泡形态
                                            </label>
                                            <Select
                                                size="small"
                                                style={{ width: '100%' }}
                                                value={selectedDraftLoc.dialogue.custom_box?.style || selectedDraftLoc.dialogue.type || 'speech'}
                                                onChange={(v) =>
                                                    updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                        const st = String(v || 'speech')
                                                        dlg.type = st
                                                        dlg.custom_box = { ...(dlg.custom_box || {}), style: st }
                                                    })
                                                }
                                            >
                                                {BUBBLE_STYLES.map((opt) => (
                                                    <Select.Option key={opt.value} value={opt.value}>
                                                        {opt.label}
                                                    </Select.Option>
                                                ))}
                                            </Select>
                                        </div>
                                        <div className="space-y-1">
                                            <label className="block text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                                尾尖方向
                                            </label>
                                            <Select
                                                size="small"
                                                style={{ width: '100%' }}
                                                value={
                                                    selectedDraftLoc.dialogue.custom_box?.tail_dir ||
                                                    selectedDraftLoc.dialogue.speaker_position ||
                                                    'center'
                                                }
                                                onChange={(v) =>
                                                    updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                        const dir = String(v || 'center')
                                                        dlg.speaker_position = dir
                                                        dlg.custom_box = { ...(dlg.custom_box || {}), tail_dir: dir }
                                                    })
                                                }
                                            >
                                                {TAIL_OPTIONS.map((opt) => (
                                                    <Select.Option key={opt.value} value={opt.value}>
                                                        {opt.label}
                                                    </Select.Option>
                                                ))}
                                            </Select>
                                        </div>
                                    </div>

                                    <div className="space-y-1 pt-1">
                                        <div className="flex items-center justify-between text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                                            <span>字号比例</span>
                                            <span className="font-mono" style={{ color: 'var(--text-primary)' }}>
                                                {((selectedDraftLoc.dialogue.custom_box?.font_scale ?? 1) * 100).toFixed(0)}%
                                            </span>
                                        </div>
                                        <Slider
                                            min={0.7}
                                            max={1.55}
                                            step={0.05}
                                            value={selectedDraftLoc.dialogue.custom_box?.font_scale ?? 1}
                                            onChange={(v) =>
                                                updateDialogueField(selectedBubble.panel_id, selectedBubble.dialogue_index, (dlg) => {
                                                    dlg.custom_box = { ...(dlg.custom_box || {}), font_scale: Number(v) }
                                                })
                                            }
                                        />
                                    </div>

                                    <div
                                        className="pt-2.5 border-t grid grid-cols-2 gap-2 text-[11px] font-mono"
                                        style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
                                    >
                                        <div>
                                            X: {((selectedDraftLoc.dialogue.custom_box?.x_pct ?? selectedBubble.x_pct) * 100).toFixed(1)}%
                                        </div>
                                        <div>
                                            Y: {((selectedDraftLoc.dialogue.custom_box?.y_pct ?? selectedBubble.y_pct) * 100).toFixed(1)}%
                                        </div>
                                    </div>
                                </div>
                            ) : null}
                        </>
                    )}

                    {inspectorTab === 'layers' && (
                        <div className="space-y-2">
                            {panelBoxes.map((pb) => {
                                const pbBubbles = bubbleLayouts.filter((b) => b.panel_id === pb.panel_id)
                                return (
                                    <div key={pb.panel_id} className="space-y-0.5">
                                        <div
                                            className="px-2 py-1 text-[11px] font-mono font-semibold flex items-center justify-between"
                                            style={{ color: 'var(--text-secondary)' }}
                                        >
                                            <span>PANEL {pb.panel_id}</span>
                                            <span style={{ color: 'var(--text-muted)' }}>{pbBubbles.length}</span>
                                        </div>
                                        {pbBubbles.map((b) => {
                                            const k = bubbleKey(b)
                                            const active = selectedBubble ? bubbleKey(selectedBubble) === k : false
                                            return (
                                                <button
                                                    key={k}
                                                    type="button"
                                                    onClick={() => {
                                                        setSelectedKey(k)
                                                        setInspectorTab('props')
                                                    }}
                                                    className="w-full text-left px-2.5 py-1.5 rounded border-0 cursor-pointer transition-colors flex items-center justify-between gap-2"
                                                    style={{
                                                        backgroundColor: active ? 'var(--accent-subtle)' : 'transparent',
                                                        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                                                    }}
                                                >
                                                    <span className="truncate text-xs">
                                                        {b.speaker ? `${b.speaker}: ` : ''}
                                                        {b.text}
                                                    </span>
                                                    <span className="text-[10px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
                                                        {b.style}
                                                    </span>
                                                </button>
                                            )
                                        })}
                                    </div>
                                )
                            })}
                        </div>
                    )}

                    {inspectorTab === 'history' && (
                        <div className="space-y-1.5">
                            {runs.length === 0 ? (
                                <div className="text-xs py-6 text-center" style={{ color: 'var(--text-muted)' }}>
                                    暂无执行记录
                                </div>
                            ) : (
                                runs.slice(0, 14).map((r) => (
                                    <div
                                        key={r.id}
                                        className="px-2.5 py-2 rounded border text-xs space-y-0.5"
                                        style={{
                                            backgroundColor: 'var(--bg-app)',
                                            borderColor: 'var(--border-subtle)',
                                        }}
                                    >
                                        <div className="flex items-center justify-between">
                                            <span className="font-mono text-[11px] font-semibold uppercase" style={{ color: 'var(--text-primary)' }}>
                                                {r.stage}
                                            </span>
                                            <span
                                                className="text-[10px] font-mono"
                                                style={{
                                                    color:
                                                        r.status === 'succeeded'
                                                            ? 'var(--status-ok)'
                                                            : r.status === 'failed'
                                                              ? 'var(--status-danger)'
                                                              : 'var(--status-warn)',
                                                }}
                                            >
                                                {r.status}
                                            </span>
                                        </div>
                                        {r.commit_message && (
                                            <div className="text-[11px] truncate" style={{ color: 'var(--text-secondary)' }}>
                                                {r.commit_message}
                                            </div>
                                        )}
                                        {r.created_at && (
                                            <div className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                                {r.created_at.slice(0, 19).replace('T', ' ')}
                                            </div>
                                        )}
                                    </div>
                                ))
                            )}
                        </div>
                    )}
                </div>
            </ResizableInspector>
        </div>
    )
}
