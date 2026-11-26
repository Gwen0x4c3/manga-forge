import { useNavigate } from 'react-router-dom'
import { Tag, Button, Empty } from '@douyinfe/semi-ui'
import { storageFileUrl } from '@/services/project'
import type { StoryBranchTreeNode } from '@/services/project'

interface Props {
    projectId: string
    branches: StoryBranchTreeNode[]
    activeBranchId: string
    onSelectBranch: (branchId: string) => void
}

const LANE_COLORS = ['#4f46e5', '#7c3aed', '#0d9488', '#e11d48', '#d97706']

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
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="text-base font-bold text-slate-900 m-0">平行世界线分支树 (Multiverse DAG)</h3>
                    <p className="text-xs text-slate-500 m-0 mt-0.5">
                        支持从任意章节 Fork 平行剧情线；每条世界线独立演化角色状态、伏笔与记忆，点击任意节点进入阅读
                    </p>
                </div>
                <Tag color="indigo">共 {branches.length} 条世界线</Tag>
            </div>

            <div className="space-y-3">
                {branches.map((branch, bIdx) => {
                    const color = LANE_COLORS[bIdx % LANE_COLORS.length]
                    const isActive = branch.id === activeBranchId
                    const parentBranch = branch.base_branch_id ? branchById.get(branch.base_branch_id) : null
                    const baseEpNo = branch.base_episode_id ? epNumberById.get(branch.base_episode_id) : null

                    return (
                        <div
                            key={branch.id}
                            className={`rounded-2xl border p-4 transition ${
                                isActive
                                    ? 'border-indigo-400 bg-indigo-50/35 shadow-sm'
                                    : 'border-slate-200 bg-white hover:border-slate-300'
                            }`}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="w-3 h-3 rounded-full inline-block" style={{ background: color }} />
                                    <span className="font-bold text-sm text-slate-900">{branch.name}</span>
                                    {branch.is_default && <Tag size="small" color="indigo">默认主线</Tag>}
                                    {parentBranch && (
                                        <Tag size="small" color="violet">
                                            Fork 自 {parentBranch.name}
                                            {baseEpNo !== null ? ` · 第 ${baseEpNo} 话` : ''}
                                        </Tag>
                                    )}
                                    <span className="text-xs text-slate-500">{branch.episode_count} 话</span>
                                </div>
                                {!isActive && (
                                    <Button size="small" onClick={() => onSelectBranch(branch.id)}>
                                        切换图谱至此分支
                                    </Button>
                                )}
                            </div>

                            {branch.episodes.length === 0 ? (
                                <div className="text-xs text-slate-400 py-2">该分支暂无章节</div>
                            ) : (
                                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                    {branch.episodes.map((ep, idx) => (
                                        <div key={ep.id} className="flex items-center gap-2 shrink-0">
                                            {idx > 0 && (
                                                <div className="w-6 h-0.5 rounded" style={{ background: color, opacity: 0.55 }} />
                                            )}
                                            <div
                                                onClick={() => navigate(`/projects/${projectId}/episodes/${ep.id}`)}
                                                className="w-40 rounded-xl border border-slate-200 bg-white hover:border-indigo-400 hover:shadow transition cursor-pointer p-2 flex items-center gap-2.5"
                                            >
                                                {ep.cover_path ? (
                                                    <img
                                                        src={storageFileUrl(ep.cover_path)}
                                                        alt={ep.title}
                                                        className="w-10 h-14 rounded-md object-cover shrink-0 border border-slate-100"
                                                    />
                                                ) : (
                                                    <div
                                                        className="w-10 h-14 rounded-md flex items-center justify-center text-[11px] font-bold text-white shrink-0"
                                                        style={{ background: color }}
                                                    >
                                                        {ep.label}
                                                    </div>
                                                )}
                                                <div className="min-w-0 flex-1 space-y-0.5">
                                                    <div className="flex items-center gap-1">
                                                        <span className="text-xs font-bold text-slate-900">第 {ep.label} 话</span>
                                                        {ep.source === 'generated' && (
                                                            <span className="text-[9px] px-1 py-0.5 rounded bg-purple-100 text-purple-700 font-bold">
                                                                AI
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="text-[11px] text-slate-600 truncate">{ep.title}</div>
                                                    <div className="text-[10px] text-slate-400">{ep.status}</div>
                                                </div>
                                            </div>
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
