import { useNavigate } from 'react-router-dom'
import { Button, Empty } from '@douyinfe/semi-ui'
import { storageFileUrl } from '@/services/project'
import type { StoryBranchTreeNode } from '@/services/project'

interface Props {
    projectId: string
    branches: StoryBranchTreeNode[]
    activeBranchId: string
    onSelectBranch: (branchId: string) => void
}

export default function BranchTreeGraph({ projectId, branches, activeBranchId, onSelectBranch }: Props) {
    const navigate = useNavigate()

    if (branches.length === 0) {
        return <Empty description="暂无世界线分支" />
    }

    const branchById = new Map(branches.map((b) => [b.id, b]))
    const epNumberById = new Map<string, number>()
    branches.forEach((b) => {
        b.episodes.forEach((ep) => epNumberById.set(ep.id, ep.number))
    })

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
                <div>
                    <h3 className="font-editorial text-base font-bold m-0" style={{ color: 'var(--text-primary)' }}>
                        平行世界线分支树
                    </h3>
                    <p className="text-xs m-0 mt-0.5" style={{ color: 'var(--text-muted)' }}>
                        从任意章节分叉出的平行剧情线独立演化角色状态、伏笔与记忆
                    </p>
                </div>
                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                    {branches.length} 条分支
                </span>
            </div>

            <div className="space-y-3">
                {branches.map((branch) => {
                    const isActive = branch.id === activeBranchId
                    const parentBranch = branch.base_branch_id ? branchById.get(branch.base_branch_id) : null
                    const baseEpNo = branch.base_episode_id ? epNumberById.get(branch.base_episode_id) : null

                    return (
                        <div
                            key={branch.id}
                            className="rounded-md border p-4 space-y-3"
                            style={{
                                backgroundColor: 'var(--bg-panel)',
                                borderColor: isActive ? 'var(--accent)' : 'var(--border)',
                            }}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2.5">
                                    <span
                                        className="w-2 h-2 rounded-full"
                                        style={{ backgroundColor: isActive ? 'var(--accent)' : 'var(--text-muted)' }}
                                    />
                                    <span className="font-mono text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                                        {branch.name}
                                    </span>
                                    {branch.is_default && (
                                        <span
                                            className="text-[10px] font-mono px-1.5 py-0.5 rounded-[3px] border"
                                            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
                                        >
                                            MAIN
                                        </span>
                                    )}
                                    {parentBranch && (
                                        <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                            Fork 自 {parentBranch.name}
                                            {baseEpNo !== null ? ` · Ep.${baseEpNo}` : ''}
                                        </span>
                                    )}
                                    <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                        {branch.episode_count} 话
                                    </span>
                                </div>
                                {!isActive && (
                                    <Button size="small" theme="light" onClick={() => onSelectBranch(branch.id)}>
                                        切换至此分支
                                    </Button>
                                )}
                            </div>

                            {branch.episodes.length === 0 ? (
                                <div className="text-xs py-1" style={{ color: 'var(--text-muted)' }}>
                                    该分支暂无章节
                                </div>
                            ) : (
                                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                    {branch.episodes.map((ep, idx) => (
                                        <div key={ep.id} className="flex items-center gap-2 shrink-0">
                                            {idx > 0 && (
                                                <div className="w-5 h-px" style={{ backgroundColor: 'var(--border)' }} />
                                            )}
                                            <button
                                                type="button"
                                                onClick={() => navigate(`/projects/${projectId}/episodes/${ep.id}`)}
                                                className="w-40 rounded border p-2 flex items-center gap-2.5 text-left cursor-pointer transition-colors hover:border-[var(--accent)]"
                                                style={{
                                                    backgroundColor: 'var(--bg-app)',
                                                    borderColor: 'var(--border-subtle)',
                                                }}
                                            >
                                                <div
                                                    className="w-9 h-12 rounded-[3px] border overflow-hidden shrink-0"
                                                    style={{ backgroundColor: 'var(--paper)', borderColor: 'var(--border)' }}
                                                >
                                                    {ep.cover_path ? (
                                                        <img
                                                            src={storageFileUrl(ep.cover_path)}
                                                            alt={ep.title}
                                                            className="w-full h-full object-cover"
                                                        />
                                                    ) : (
                                                        <div className="w-full h-full flex items-center justify-center font-mono text-[10px] text-[#18181B]">
                                                            {ep.label}
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="min-w-0 flex-1 space-y-0.5">
                                                    <div className="flex items-center gap-1 font-mono text-[11px]">
                                                        <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>
                                                            Ep.{ep.label}
                                                        </span>
                                                        {ep.source === 'generated' && (
                                                            <span style={{ color: 'var(--accent)', fontSize: 9 }}>续画</span>
                                                        )}
                                                    </div>
                                                    <div className="text-[11px] truncate" style={{ color: 'var(--text-secondary)' }}>
                                                        {ep.title}
                                                    </div>
                                                    <div className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                                                        {ep.status}
                                                    </div>
                                                </div>
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
