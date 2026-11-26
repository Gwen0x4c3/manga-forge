import { useRef, type ReactNode } from 'react'
import { useAppStore } from '@/stores/app'
import { IconInspectorToggle } from './StudioIcons'

interface Props {
    title: string
    subtitle?: string
    headerExtra?: ReactNode
    children: ReactNode
}

export default function ResizableInspector({ title, subtitle, headerExtra, children }: Props) {
    const { inspectorOpen, inspectorWidth, toggleInspector, setInspectorWidth } = useAppStore()
    const dragRef = useRef<{ startX: number; startW: number } | null>(null)

    const onResizeDown = (e: React.PointerEvent) => {
        e.preventDefault()
        dragRef.current = { startX: e.clientX, startW: inspectorWidth }
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    }

    const onResizeMove = (e: React.PointerEvent) => {
        if (!dragRef.current) return
        const delta = dragRef.current.startX - e.clientX
        setInspectorWidth(dragRef.current.startW + delta)
    }

    const onResizeUp = () => {
        dragRef.current = null
    }

    if (!inspectorOpen) {
        return (
            <div
                className="w-10 shrink-0 border-l flex flex-col items-center py-2.5 gap-2"
                style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border)' }}
            >
                <button
                    type="button"
                    title={`展开 ${title}`}
                    onClick={toggleInspector}
                    className="w-7 h-7 rounded flex items-center justify-center border-0 bg-transparent cursor-pointer transition-colors"
                    style={{ color: 'var(--text-secondary)' }}
                >
                    <IconInspectorToggle size={15} />
                </button>
                <span
                    className="text-[11px] font-medium tracking-wider select-none"
                    style={{ color: 'var(--text-muted)', writingMode: 'vertical-rl' }}
                >
                    {title}
                </span>
            </div>
        )
    }

    return (
        <aside
            className="shrink-0 border-l flex flex-col relative h-full min-h-0"
            style={{
                width: inspectorWidth,
                backgroundColor: 'var(--bg-panel)',
                borderColor: 'var(--border)',
            }}
        >
            {/* Left Drag Resize Handle */}
            <div
                onPointerDown={onResizeDown}
                onPointerMove={onResizeMove}
                onPointerUp={onResizeUp}
                title="拖拽调整属性栏宽度"
                className="absolute top-0 bottom-0 -left-1 w-2 cursor-col-resize z-20 group"
            >
                <div className="w-[2px] h-full mx-auto bg-transparent group-hover:bg-[#E64B35] transition-colors" />
            </div>

            {/* Inspector Header */}
            <div
                className="h-10 px-3.5 border-b flex items-center justify-between gap-2 shrink-0"
                style={{ borderColor: 'var(--border)' }}
            >
                <div className="min-w-0 flex items-center gap-2">
                    <span className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>
                        {title}
                    </span>
                    {subtitle && (
                        <span className="text-[11px] truncate" style={{ color: 'var(--text-muted)' }}>
                            {subtitle}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                    {headerExtra}
                    <button
                        type="button"
                        title="折叠右侧面板"
                        onClick={toggleInspector}
                        className="w-6 h-6 rounded flex items-center justify-center border-0 bg-transparent hover:bg-[var(--bg-hover)] cursor-pointer transition-colors"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <IconInspectorToggle size={14} />
                    </button>
                </div>
            </div>

            {/* Scrollable Body */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3.5">{children}</div>
        </aside>
    )
}
