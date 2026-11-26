import { useState, useRef } from 'react'
import { Modal, Select, Button, Toast } from '@douyinfe/semi-ui'
import { assetImageService, storageFileUrl } from '@/services/project'
import type { Asset, EpisodePage } from '@/services/project'

interface Props {
    visible: boolean
    episodeId: string
    page: EpisodePage | null
    assets: Asset[]
    onClose: () => void
    onCropped: () => void
}

export default function PageCropModal({ visible, episodeId, page, assets, onClose, onCropped }: Props) {
    const [targetAssetId, setTargetAssetId] = useState<string | undefined>(assets[0]?.id)
    const [kind, setKind] = useState<string>('reference')
    const [bbox, setBbox] = useState<[number, number, number, number] | null>(null)
    const [saving, setSaving] = useState(false)

    const containerRef = useRef<HTMLDivElement | null>(null)
    const dragStartRef = useRef<{ x: number; y: number } | null>(null)

    const getNormPoint = (e: React.PointerEvent): { x: number; y: number } | null => {
        const rect = containerRef.current?.getBoundingClientRect()
        if (!rect || rect.width === 0 || rect.height === 0) return null
        return {
            x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
            y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
        }
    }

    const handlePointerDown = (e: React.PointerEvent) => {
        const pt = getNormPoint(e)
        if (!pt) return
        dragStartRef.current = pt
        setBbox([pt.x, pt.y, pt.x, pt.y])
        ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    }

    const handlePointerMove = (e: React.PointerEvent) => {
        const start = dragStartRef.current
        if (!start) return
        const pt = getNormPoint(e)
        if (!pt) return
        setBbox([
            Math.min(start.x, pt.x),
            Math.min(start.y, pt.y),
            Math.max(start.x, pt.x),
            Math.max(start.y, pt.y),
        ])
    }

    const handlePointerUp = () => {
        dragStartRef.current = null
    }

    const handleSubmit = async () => {
        if (!page) return
        const assetId = targetAssetId || assets[0]?.id
        if (!assetId) {
            Toast.warning('请先选择一个目标资产')
            return
        }
        if (!bbox || bbox[2] - bbox[0] < 0.02 || bbox[3] - bbox[1] < 0.02) {
            Toast.warning('请在原作页面上按住鼠标左键拖拽框选出要裁切的区域')
            return
        }
        setSaving(true)
        try {
            await assetImageService.cropFromPage(assetId, {
                episode_id: episodeId,
                page_index: page.page_index,
                bbox,
                kind,
            })
            Toast.success('已裁切高保真参考图并存入资产图库')
            setBbox(null)
            onCropped()
            onClose()
        } catch {
            Toast.error('裁切保存失败，请重试')
        } finally {
            setSaving(false)
        }
    }

    return (
        <Modal
            title={page ? `框选原作第 ${page.page_index + 1} 页裁切为角色/道具参考图` : '框选裁图入库'}
            visible={visible}
            onCancel={onClose}
            width={820}
            footer={
                <div className="flex items-center justify-between">
                    <div className="text-xs text-[var(--text-muted)]">
                        {bbox
                            ? `已选区域：x=${(bbox[0] * 100).toFixed(0)}%–${(bbox[2] * 100).toFixed(0)}%, y=${(bbox[1] * 100).toFixed(0)}%–${(bbox[3] * 100).toFixed(0)}%`
                            : '在下方图片上按住鼠标左键拖动，即可框选角色特写或道具参考图'}
                    </div>
                    <div className="flex gap-2">
                        <Button onClick={onClose}>取消</Button>
                        <Button theme="solid" loading={saving} onClick={handleSubmit}>
                            裁切并存入资产库
                        </Button>
                    </div>
                </div>
            }
        >
            {page && (
                <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 bg-[var(--bg-elevated)] p-3 rounded-[6px] border border-[var(--border)]">
                        <div className="md:col-span-2">
                            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">归属目标资产</label>
                            <Select
                                filter
                                style={{ width: '100%' }}
                                value={targetAssetId || assets[0]?.id}
                                onChange={(v) => setTargetAssetId(String(v))}
                                placeholder="选择角色、服装、道具或场景资产"
                            >
                                {assets.map((a) => (
                                    <Select.Option key={a.id} value={a.id}>
                                        [{a.type}] {a.name}
                                    </Select.Option>
                                ))}
                            </Select>
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-[var(--text-secondary)] mb-1">参考图用途</label>
                            <Select style={{ width: '100%' }} value={kind} onChange={(v) => setKind(String(v))}>
                                <Select.Option value="reference">主参考图 (Reference)</Select.Option>
                                <Select.Option value="turnaround">设定视图 (Turnaround)</Select.Option>
                                <Select.Option value="thumbnail">缩略头像 (Thumbnail)</Select.Option>
                            </Select>
                        </div>
                    </div>

                    <div className="flex justify-center bg-[var(--bg-canvas)] border border-[var(--border)] rounded-[6px] p-3 max-h-[60vh] overflow-y-auto">
                        <div
                            ref={containerRef}
                            onPointerDown={handlePointerDown}
                            onPointerMove={handlePointerMove}
                            onPointerUp={handlePointerUp}
                            className="relative inline-block cursor-crosshair select-none max-w-full"
                        >
                            <img
                                src={storageFileUrl(page.image_path)}
                                alt={`Crop Page ${page.page_index + 1}`}
                                className="max-h-[54vh] w-auto block rounded-[4px] pointer-events-none"
                            />
                            {bbox && (
                                <div
                                    className="absolute border-2 border-[var(--accent)] bg-[var(--accent-soft)] pointer-events-none"
                                    style={{
                                        left: `${bbox[0] * 100}%`,
                                        top: `${bbox[1] * 100}%`,
                                        width: `${(bbox[2] - bbox[0]) * 100}%`,
                                        height: `${(bbox[3] - bbox[1]) * 100}%`,
                                    }}
                                >
                                    <span className="absolute -top-5 left-0 px-1.5 py-0.5 rounded-[4px] bg-[var(--accent)] text-white text-[10px] font-medium">
                                        裁切框
                                    </span>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </Modal>
    )
}
