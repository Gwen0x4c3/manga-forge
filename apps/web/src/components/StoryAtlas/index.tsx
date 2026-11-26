import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Spin, Empty, Select } from '@douyinfe/semi-ui'
import { memoryService } from '@/services/project'
import CharacterGraph from './CharacterGraph'
import PitSwimlaneTimeline from './PitSwimlaneTimeline'
import BranchTreeGraph from './BranchTreeGraph'
import StoryDetectivePanel from './StoryDetectivePanel'

export type AtlasMode = 'characters' | 'pits' | 'qa' | 'branches'

interface Props {
    projectId: string
    defaultBranchId?: string
    mode: AtlasMode
}

export default function StoryAtlas({ projectId, defaultBranchId, mode }: Props) {
    const [branchId, setBranchId] = useState<string | undefined>(defaultBranchId)

    const { data, isLoading, refetch, isFetching } = useQuery({
        queryKey: ['story-graph', projectId, branchId],
        queryFn: () => memoryService.getGraph(projectId, branchId),
        enabled: !!projectId,
    })

    if (isLoading) {
        return (
            <div className="flex-1 flex items-center justify-center py-20">
                <Spin size="large" />
            </div>
        )
    }

    if (!data) {
        return (
            <div className="flex-1 flex items-center justify-center py-20">
                <Empty description="无法加载故事数据" />
            </div>
        )
    }

    const openPits = data.timeline.pit_swimlanes.filter((p) => p.status !== 'resolved').length
    const resolvedPits = data.timeline.pit_swimlanes.filter((p) => p.status === 'resolved').length

    return (
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* Compact Editorial Summary Strip (replaces KPI cards) */}
            <div
                className="h-10 shrink-0 px-4 border-b flex items-center justify-between gap-4 text-[13px]"
                style={{ backgroundColor: 'var(--bg-app)', borderColor: 'var(--border)' }}
            >
                <div className="flex items-center gap-3 font-mono truncate" style={{ color: 'var(--text-secondary)' }}>
                    <span className="font-sans font-semibold" style={{ color: 'var(--text-primary)' }}>
                        {data.project_title}
                    </span>
                    <span style={{ color: 'var(--border)' }}>|</span>
                    <span>{data.character_graph.nodes.length} 人物</span>
                    <span>·</span>
                    <span>{data.character_graph.edges.length} 关系</span>
                    <span>·</span>
                    <span>{data.timeline.episodes.length} 章节</span>
                    <span>·</span>
                    <span>
                        伏笔 {openPits} 待填 / {resolvedPits} 已填
                    </span>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                    <Select
                        size="small"
                        value={branchId || data.branch_id}
                        onChange={(v) => setBranchId(v ? String(v) : undefined)}
                        style={{ width: 150 }}
                    >
                        {data.branch_tree.map((b) => (
                            <Select.Option key={b.id} value={b.id}>
                                {b.name}
                                {b.is_default ? ' (main)' : ''}
                            </Select.Option>
                        ))}
                    </Select>
                    <button
                        type="button"
                        onClick={() => refetch()}
                        disabled={isFetching}
                        className="h-6 px-2 rounded border text-[11px] cursor-pointer hover:bg-[var(--bg-hover)]"
                        style={{
                            backgroundColor: 'transparent',
                            borderColor: 'var(--border)',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        {isFetching ? '刷新中' : '刷新'}
                    </button>
                </div>
            </div>

            {mode === 'characters' && (
                <CharacterGraph
                    nodes={data.character_graph.nodes}
                    edges={data.character_graph.edges}
                    onStatusUpdated={() => refetch()}
                />
            )}

            {mode === 'pits' && (
                <PitSwimlaneTimeline
                    projectId={projectId}
                    episodes={data.timeline.episodes}
                    arcs={data.timeline.arcs}
                    pits={data.timeline.pit_swimlanes}
                    storyBible={data.story_bible}
                />
            )}

            {mode === 'qa' && (
                <StoryDetectivePanel
                    projectId={projectId}
                    branchId={data.branch_id}
                    characters={data.character_graph.nodes}
                />
            )}

            {mode === 'branches' && (
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="max-w-[1280px] mx-auto">
                        <BranchTreeGraph
                            projectId={projectId}
                            branches={data.branch_tree}
                            activeBranchId={data.branch_id}
                            onSelectBranch={(bid) => setBranchId(bid)}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
