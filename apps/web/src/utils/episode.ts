/**
 * Format an episode label cleanly for display.
 * - Pure numeric labels ("75", "75.5") -> "第 75 话"
 * - Unnumbered / "none" / "null" -> "番外"
 * - Descriptive extra labels ("Vol.0 番外", "番外", "Extra 1") -> shown directly without "第 ... 话"
 */
export function formatEpisodeLabel(
    label?: string | null,
    number?: number | string | null,
): string {
    const raw = (label ?? '').trim()
    const lowered = raw.toLowerCase()
    if (!raw || lowered === 'none' || lowered === 'null') {
        const num = Number(number)
        if (Number.isFinite(num) && num < 10000) {
            return `第 ${number} 话`
        }
        return '番外'
    }
    if (/^\d+(?:\.\d+)?$/.test(raw)) {
        return `第 ${raw} 话`
    }
    if (/^(第|Vol\.|SP|Extra|Omake|番外|外传|特别篇)/i.test(raw) || /番外|外传|特别篇/i.test(raw)) {
        return raw
    }
    return `第 ${raw} 话`
}
