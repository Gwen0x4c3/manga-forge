import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function baseProps(size: number, props: SVGProps<SVGSVGElement>) {
    return {
        width: size,
        height: size,
        viewBox: '0 0 20 20',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.5,
        strokeLinecap: 'round' as const,
        strokeLinejoin: 'round' as const,
        ...props,
    }
}

/** Custom MangaForge Mark: Japanese manga panel gutters + vermilion editorial crop mark */
export function MangaForgeLogo({ size = 20, className }: { size?: number; className?: string }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            {/* Outer print crop border */}
            <rect x="2.5" y="2.5" width="19" height="19" rx="2" stroke="currentColor" strokeWidth="1.6" />
            {/* Asymmetric manga panel gutters */}
            <line x1="2.5" y1="10.5" x2="21.5" y2="10.5" stroke="currentColor" strokeWidth="1.5" />
            <line x1="13" y1="10.5" x2="11" y2="21.5" stroke="currentColor" strokeWidth="1.5" />
            {/* Editorial vermilion redline accent panel */}
            <rect x="4.5" y="4.5" width="5.5" height="4" rx="0.5" fill="#E64B35" />
            {/* Subtle print registration corner tick */}
            <path d="M18.5 5.5H16.5M18.5 5.5V7.5" stroke="#E64B35" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
    )
}

export function IconChapters({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <rect x="3" y="3" width="14" height="14" rx="1.5" />
            <line x1="3" y1="8.5" x2="17" y2="8.5" />
            <line x1="10" y1="8.5" x2="10" y2="17" />
        </svg>
    )
}

export function IconGraph({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="5.5" cy="5.5" r="2.2" />
            <circle cx="14.5" cy="5.5" r="2.2" />
            <circle cx="10" cy="14.5" r="2.5" />
            <line x1="7.5" y1="6.4" x2="12.5" y2="6.4" />
            <line x1="6.7" y1="7.5" x2="8.8" y2="12.2" />
            <line x1="13.3" y1="7.5" x2="11.2" y2="12.2" />
        </svg>
    )
}

export function IconTimeline({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <line x1="3" y1="5.5" x2="13" y2="5.5" />
            <line x1="7" y1="10" x2="17" y2="10" />
            <line x1="4.5" y1="14.5" x2="11.5" y2="14.5" />
            <circle cx="13" cy="5.5" r="1.5" fill="currentColor" stroke="none" />
            <circle cx="7" cy="10" r="1.5" fill="currentColor" stroke="none" />
            <circle cx="11.5" cy="14.5" r="1.5" fill="currentColor" stroke="none" />
        </svg>
    )
}

export function IconResearch({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="9" cy="9" r="5.5" />
            <line x1="13.2" y1="13.2" x2="17" y2="17" />
            <line x1="6.8" y1="9" x2="11.2" y2="9" />
            <line x1="9" y1="6.8" x2="9" y2="11.2" />
        </svg>
    )
}

export function IconBook({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M3.5 4.2C3.5 3.5 4 3 4.7 3H9.5V16.5H4.7C4 16.5 3.5 16 3.5 15.3V4.2Z" />
            <path d="M16.5 4.2C16.5 3.5 16 3 15.3 3H10.5V16.5H15.3C16 16.5 16.5 16 16.5 15.3V4.2Z" />
        </svg>
    )
}

export function IconBranch({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="5.5" cy="4.5" r="2" />
            <circle cx="5.5" cy="15.5" r="2" />
            <circle cx="14.5" cy="8" r="2" />
            <line x1="5.5" y1="6.5" x2="5.5" y2="13.5" />
            <path d="M5.5 12C5.5 9.8 14.5 11.2 14.5 10" />
        </svg>
    )
}

export function IconAssets({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <rect x="3" y="3" width="6" height="6" rx="1" />
            <rect x="11" y="3" width="6" height="6" rx="1" />
            <rect x="3" y="11" width="6" height="6" rx="1" />
            <rect x="11" y="11" width="6" height="6" rx="1" />
        </svg>
    )
}

export function IconHome({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M3 9.2L10 3.2L17 9.2" />
            <path d="M5 8V16.5H15V8" />
        </svg>
    )
}

export function IconSidebarToggle({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <rect x="2.5" y="3.5" width="15" height="13" rx="1.5" />
            <line x1="7" y1="3.5" x2="7" y2="16.5" />
        </svg>
    )
}

export function IconInspectorToggle({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <rect x="2.5" y="3.5" width="15" height="13" rx="1.5" />
            <line x1="13" y1="3.5" x2="13" y2="16.5" />
        </svg>
    )
}

export function IconSun({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="10" cy="10" r="3.2" />
            <path d="M10 2.5V4.2M10 15.8V17.5M2.5 10H4.2M15.8 10H17.5M4.7 4.7L5.9 5.9M14.1 14.1L15.3 15.3M15.3 4.7L14.1 5.9M5.9 14.1L4.7 15.3" />
        </svg>
    )
}

export function IconMoon({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M15.8 12.2A6.5 6.5 0 0 1 7.8 4.2A6.5 6.5 0 1 0 15.8 12.2Z" />
        </svg>
    )
}

export function IconZoomIn({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="9" cy="9" r="5.5" />
            <line x1="13.2" y1="13.2" x2="16.8" y2="16.8" />
            <line x1="9" y1="6.5" x2="9" y2="11.5" />
            <line x1="6.5" y1="9" x2="11.5" y2="9" />
        </svg>
    )
}

export function IconZoomOut({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <circle cx="9" cy="9" r="5.5" />
            <line x1="13.2" y1="13.2" x2="16.8" y2="16.8" />
            <line x1="6.5" y1="9" x2="11.5" y2="9" />
        </svg>
    )
}

export function IconFit({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M3.5 7V3.5H7M13 3.5H16.5V7M16.5 13V16.5H13M7 16.5H3.5V13" />
        </svg>
    )
}

export function IconLayers({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M10 3L17 6.8L10 10.6L3 6.8L10 3Z" />
            <path d="M3 10.2L10 14L17 10.2" />
            <path d="M3 13.5L10 17.3L17 13.5" />
        </svg>
    )
}

export function IconHistory({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M4 10A6 6 0 1 0 5.8 5.7" />
            <polyline points="4 3.5 4 6.8 7.3 6.8" />
            <polyline points="10 6.8 10 10.2 12.6 11.6" />
        </svg>
    )
}

export function IconSliders({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <line x1="3" y1="5.5" x2="17" y2="5.5" />
            <circle cx="7" cy="5.5" r="1.6" fill="var(--bg-panel)" />
            <line x1="3" y1="10" x2="17" y2="10" />
            <circle cx="13" cy="10" r="1.6" fill="var(--bg-panel)" />
            <line x1="3" y1="14.5" x2="17" y2="14.5" />
            <circle cx="8.5" cy="14.5" r="1.6" fill="var(--bg-panel)" />
        </svg>
    )
}

export function IconDownload({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M10 3V12.5" />
            <polyline points="6.5 9.2 10 12.8 13.5 9.2" />
            <path d="M3.5 15.5H16.5" />
        </svg>
    )
}

export function IconExternal({ size = 13, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M11.5 3.5H16.5V8.5" />
            <line x1="16.5" y1="3.5" x2="9.5" y2="10.5" />
            <path d="M14.5 11.5V15.5C14.5 16 14 16.5 13.5 16.5H4.5C4 16.5 3.5 16 3.5 15.5V6.5C3.5 6 4 5.5 4.5 5.5H8.5" />
        </svg>
    )
}

export function IconPlus({ size = 14, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <line x1="10" y1="4" x2="10" y2="16" />
            <line x1="4" y1="10" x2="16" y2="10" />
        </svg>
    )
}

export function IconImport({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <path d="M10 13V3.5" />
            <polyline points="6.8 6.8 10 3.5 13.2 6.8" />
            <path d="M3.5 12.5V15.5C3.5 16 4 16.5 4.5 16.5H15.5C16 16.5 16.5 16 16.5 15.5V12.5" />
        </svg>
    )
}

export function IconTelemetry({ size = 15, ...props }: IconProps) {
    return (
        <svg {...baseProps(size, props)}>
            <polyline points="2.5 11.5 6 11.5 8.2 5.5 11.5 14.5 13.8 9 17.5 9" />
        </svg>
    )
}
