import { useState, useRef, useEffect } from 'react'
import { Button, Input, TextArea, Select, Slider, Tag, RadioGroup, Switch, Toast } from '@douyinfe/semi-ui'
import { IconRefresh, IconDownload } from '@douyinfe/semi-icons'
import { storageFileUrl } from '@/services/project'
import type { BubbleCustomBox, BubbleLayoutItem, ComposedPage, Storyboard } from '@/services/project'

interface Props {
    episodeId: string
    pages: ComposedPage[]
    storyboard: Storyboard | null
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

export default function BubbleCanvasEditor({
    episodeId,
    pages,
    storyboard,
    writingMode,
    onWritingModeChange,
    onApplyAndRecompose,
    recomposing,
}: Props) {
    const [activePageNo, setActivePageNo] = useState<number>(pages[0]?.page_number || 1)
    const [showOverlay, setShowOverlay] = useState<boolean>(true)
    const [selectedKey, setSelectedKey] = useState<string | null>(null)
    const [localStoryboard, setLocalStoryboard] = useState<Storyboard | null>(() =>
        storyboard ? structuredClone(storyboard) : null,
    )
    const [dragOverrides, setDragOverrides] = useState<Record<string, { pageX: number; pageY: number }>>({})
    const canvasRef = useRef<HTMLDivElement | null>(null)
    const dragStateRef = useRef<{
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

    const handlePointerDown = (e: React.PointerEvent, bubble: BubbleLayoutItem) => {
        e.stopPropagation()
        const key = bubbleKey(bubble)
        setSelectedKey(key)
        const currentPos = dragOverrides[key] || { pageX: bubble.page_x_pct, pageY: bubble.page_y_pct }
        dragStateRef.current = {
            key,
            bubble,
            startClientX: e.clientX,
            startClientY: e.clientY,
            origPageX: currentPos.pageX,
            origPageY: currentPos.pageY,
        }
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    }

    const handlePointerMove = (e: React.PointerEvent) => {
        const st = dragStateRef.current
        const rect = canvasRef.current?.getBoundingClientRect()
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

    const handlePointerUp = () => {
        const st = dragStateRef.current
        if (!st) return
        dragStateRef.current = null
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

    const handleSyncRecompose = async () => {
        if (!localStoryboard) {
            Toast.warning('未找到对应分镜数据')
            return
        }
        await onApplyAndRecompose(localStoryboard, writingMode)
    }

    return (
        <div className="space-y-4">
            {/* Top Lettering & Export Toolbar */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3.5 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-slate-600">排版方向：</span>
                        <RadioGroup
                            type="button"
                            buttonSize="small"
                            value={writingMode}
                            onChange={(e) => onWritingModeChange(e.target.value as 'horizontal' | 'vertical')}
                            options={[
                                { label: '传统日漫竖排 (Vertical)', value: 'vertical' },
                                { label: '现代横排 (Horizontal)', value: 'horizontal' },
                            ]}
                        />
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-slate-600">
                        <span>拖拽气泡热区</span>
                        <Switch size="small" checked={showOverlay} onChange={setShowOverlay} />
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <Button
                        theme="solid"
                        size="small"
                        icon={<IconRefresh />}
                        loading={recomposing}
                        onClick={handleSyncRecompose}
                    >
                        应用气泡修改并实时重排
                    </Button>
                    <Button
                        size="small"
                        icon={<IconDownload />}
                        onClick={() =>
                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=pdf`, '_blank')
                        }
                    >
                        PDF
                    </Button>
                    <Button
                        size="small"
                        icon={<IconDownload />}
                        onClick={() =>
                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=cbz`, '_blank')
                        }
                    >
                        CBZ (漫画包)
                    </Button>
                    <Button
                        size="small"
                        icon={<IconDownload />}
                        onClick={() =>
                            window.open(`/api/v1/generation/episodes/${episodeId}/export?format=webtoon`, '_blank')
                        }
                    >
                        长条漫 PNG
                    </Button>
                </div>
            </div>

            {/* Page Switcher Pills */}
            {pages.length > 1 && (
                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                    {pages.map((p) => (
                        <Button
                            key={p.page_number}
                            size="small"
                            theme={p.page_number === currentPage.page_number ? 'solid' : 'light'}
                            onClick={() => {
                                setActivePageNo(p.page_number)
                                setSelectedKey(null)
                            }}
                        >
                            第 {p.page_number} 页 · {p.layout}
                            {p.writing_mode === 'vertical' ? ' (竖排)' : ''}
                        </Button>
                    ))}
                </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
                {/* Interactive Composed Page Canvas */}
                <div className="xl:col-span-8 manga-paper-bg rounded-2xl p-4 flex justify-center">
                    <div
                        ref={canvasRef}
                        className="relative w-full max-w-2xl bg-white rounded-lg shadow-lg overflow-hidden border border-slate-200 select-none"
                    >
                        <img
                            src={storageFileUrl(currentPage.image_path)}
                            alt={`Composed Page ${currentPage.page_number}`}
                            className="w-full block pointer-events-none"
                        />

                        {showOverlay && (
                            <div className="absolute inset-0">
                                {/* Subtle panel borders — badge at bottom-right so it never covers top bubbles */}
                                {panelBoxes.map((pb) => (
                                    <div
                                        key={pb.panel_id}
                                        className="absolute border border-indigo-400/20 pointer-events-none"
                                        style={{
                                            left: `${pb.x_pct * 100}%`,
                                            top: `${pb.y_pct * 100}%`,
                                            width: `${pb.w_pct * 100}%`,
                                            height: `${pb.h_pct * 100}%`,
                                        }}
                                    >
                                        <span className="absolute bottom-1 right-1 bg-slate-900/65 text-white text-[9px] font-bold px-1.5 py-0.5 rounded">
                                            Panel {pb.panel_id}
                                        </span>
                                    </div>
                                ))}

                                {/* Draggable Bubble Anchor Handles — pill only on active bubble so text stays clean */}
                                {bubbleLayouts.map((b) => {
                                    const key = bubbleKey(b)
                                    const isSel = selectedBubble ? bubbleKey(selectedBubble) === key : false
                                    const pos = dragOverrides[key] || { pageX: b.page_x_pct, pageY: b.page_y_pct }
                                    return (
                                        <div
                                            key={key}
                                            onPointerDown={(e) => handlePointerDown(e, b)}
                                            onPointerMove={handlePointerMove}
                                            onPointerUp={handlePointerUp}
                                            title="按住拖动调整气泡位置，点击编辑样式与台词"
                                            className={`absolute rounded-lg cursor-grab active:cursor-grabbing transition-colors ${
                                                isSel
                                                    ? 'border-2 border-indigo-600 bg-indigo-500/10 shadow-md ring-2 ring-indigo-300/60'
                                                    : 'border border-dashed border-amber-500/75 bg-amber-400/5 hover:border-indigo-500 hover:bg-indigo-400/10'
                                            }`}
                                            style={{
                                                left: `${pos.pageX * 100}%`,
                                                top: `${pos.pageY * 100}%`,
                                                width: `${Math.max(5, b.page_w_pct * 100)}%`,
                                                height: `${Math.max(4, b.page_h_pct * 100)}%`,
                                            }}
                                        >
                                            {isSel && (
                                                <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-700 text-white whitespace-nowrap shadow pointer-events-none">
                                                    {b.speaker || b.panel_id} · {b.style} (可拖拽)
                                                </span>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                </div>

                {/* Right-side Bubble Inspector */}
                <div className="xl:col-span-4 rounded-2xl border border-slate-200 bg-white p-4 space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
                        <div>
                            <div className="text-sm font-bold text-slate-900">交互气泡精修面板</div>
                            <div className="text-[11px] text-slate-500">
                                拖动左侧虚线框微调坐标，点击「实时重排」即可毫秒级刷新成稿
                            </div>
                        </div>
                        <Tag size="small" color="indigo">
                            {bubbleLayouts.length} 个气泡
                        </Tag>
                    </div>

                    {bubbleLayouts.length === 0 ? (
                        <div className="text-xs text-slate-500 py-4 space-y-2">
                            <div>当前页面暂无可编辑的气泡坐标数据。</div>
                            <div>点击上方「应用气泡修改并实时重排」可立即生成支持拖拽的竖排 / 横排成稿。</div>
                        </div>
                    ) : selectedBubble && selectedDraftLoc ? (
                        <div className="space-y-3.5 text-xs">
                            <div className="flex flex-wrap gap-1.5">
                                {bubbleLayouts.map((b) => {
                                    const k = bubbleKey(b)
                                    const active = bubbleKey(selectedBubble) === k
                                    return (
                                        <button
                                            key={k}
                                            type="button"
                                            onClick={() => setSelectedKey(k)}
                                            className={`px-2 py-1 rounded-md border text-[11px] cursor-pointer transition ${
                                                active
                                                    ? 'bg-indigo-600 text-white border-indigo-600 font-bold'
                                                    : 'bg-slate-50 text-slate-700 border-slate-200 hover:border-indigo-300'
                                            }`}
                                        >
                                            {b.panel_id} #{b.dialogue_index + 1}
                                        </button>
                                    )
                                })}
                            </div>

                            <div>
                                <label className="block text-[11px] font-semibold text-slate-600 mb-1">说话人</label>
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

                            <div>
                                <label className="block text-[11px] font-semibold text-slate-600 mb-1">气泡台词文本</label>
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
                                <div>
                                    <label className="block text-[11px] font-semibold text-slate-600 mb-1">气泡形状样式</label>
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
                                <div>
                                    <label className="block text-[11px] font-semibold text-slate-600 mb-1">尾巴指向</label>
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

                            <div>
                                <div className="flex items-center justify-between text-[11px] font-semibold text-slate-600 mb-1">
                                    <span>字号缩放倍数</span>
                                    <span className="text-indigo-700">
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

                            <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                                <span className="text-[11px] text-slate-500">
                                    格内坐标：({((selectedDraftLoc.dialogue.custom_box?.x_pct ?? selectedBubble.x_pct) * 100).toFixed(0)}%,{' '}
                                    {((selectedDraftLoc.dialogue.custom_box?.y_pct ?? selectedBubble.y_pct) * 100).toFixed(0)}%)
                                </span>
                                <Button
                                    size="small"
                                    theme="borderless"
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
                                >
                                    重置自动避让坐标
                                </Button>
                            </div>
                        </div>
                    ) : (
                        <div className="text-xs text-slate-400">点击左侧任意气泡框进行精修。</div>
                    )}
                </div>
            </div>
        </div>
    )
}
