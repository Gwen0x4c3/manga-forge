import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Spin, Empty, Select, RadioGroup, Button } from '@douyinfe/semi-ui'
import { IconRefresh } from '@douyinfe/semi-icons'
import { memoryService } from '@/services/project'
import CharacterGraph from './CharacterGraph'
import PitSwimlaneTimeline from './PitSwimlaneTimeline'
import BranchTreeGraph from './BranchTreeGraph'
import StoryDetectivePanel from './StoryDetectivePanel'

interface Props {
    projectId: string
    defaultBranchId?: string
}

type AtlasSection = 'all' | 'characters' | 'timeline' | 'branches' | 'detective'

export default function StoryAtlas({ projectId, defaultBranchId }: Props) {
    const [branchId, setBranchId] = useState<string | undefined>(defaultBranchId)
    const [section, setSection] = useState<AtlasSection>('all')

    const { data, isLoading, refetch, isFetching } = useQuery({
        queryKey: ['story-graph', projectId, branchId],
        queryFn: () => memoryService.getGraph(projectId, branchId),
        enabled: !!projectId,
    })

    if (isLoading) {
        return (
            <div className="py-16 flex justify-center">
                <Spin size="large" />
            </div>
        )
    }

    if (!data) {
        return <Empty description="无法加载故事宇宙图谱" />
    }

    const openPits = data.timeline.pit_swimlanes.filter((p) => p.status === 'open').length
    const resolvedPits = data.timeline.pit_swimlanes.filter((p) => p.status === 'resolved').length

    return (
        <div className="space-y-6 pt-2">
            {/* Top Controls & Telemetry Strip */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-50 rounded-2xl p-3.5 border border-slate-200">
                <div className="flex flex-wrap items-center gap-3">
                    <RadioGroup
                        type="button"
                        value={section}
                        onChange={(e) => setSection(e.target.value as AtlasSection)}
                        options={[
                            { label: '全景图谱', value: 'all' },
                            { label: `人物星图 (${data.character_graph.nodes.length})`, value: 'characters' },
                            { label: `篇章与伏笔 (${data.timeline.pit_swimlanes.length})`, value: 'timeline' },
                            { label: `世界线树 (${data.branch_tree.length})`, value: 'branches' },
                            { label: '剧情侦探 QA', value: 'detective' },
                        ]}
                    />
                </div>
                <div className="flex items-center gap-2">
                    <Select
                        size="small"
                        value={branchId || data.branch_id}
                        onChange={(v) => setBranchId(v ? String(v) : undefined)}
                        style={{ width: 170 }}
                    >
                        {data.branch_tree.map((b) => (
                            <Select.Option key={b.id} value={b.id}>
                                {b.name} {b.is_default ? '(主线)' : ''}
                            </Select.Option>
                        ))}
                    </Select>
                    <Button size="small" icon={<IconRefresh />} loading={isFetching} onClick={() => refetch()}>
                        刷新图谱
                    </Button>
                </div>
            </div>

            {/* Compact KPI Banner */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <div className="rounded-xl bg-white border border-slate-200 px-3.5 py-2.5">
                    <div className="text-[11px] text-slate-500">人物实体节点</div>
                    <div className="text-lg font-extrabold text-indigo-700">{data.character_graph.nodes.length}</div>
                </div>
                <div className="rounded-xl bg-white border border-slate-200 px-3.5 py-2.5">
                    <div className="text-[11px] text-slate-500">共现关系连线</div>
                    <div className="text-lg font-extrabold text-violet-700">{data.character_graph.edges.length}</div>
                </div>
                <div className="rounded-xl bg-white border border-slate-200 px-3.5 py-2.5">
                    <div className="text-[11px] text-slate-500">分支连载章节</div>
                    <div className="text-lg font-extrabold text-slate-900">{data.timeline.episodes.length}</div>
                </div>
                <div className="rounded-xl bg-white border border-slate-200 px-3.5 py-2.5">
                    <div className="text-[11px] text-slate-500">伏笔待填 / 已填</div>
                    <div className="text-lg font-extrabold text-amber-600">
                        {openPits} <span className="text-xs font-semibold text-emerald-600">/ {resolvedPits}</span>
                    </div>
                </div>
                <div className="rounded-xl bg-white border border-slate-200 px-3.5 py-2.5">
                    <div className="text-[11px] text-slate-500">平行世界线</div>
                    <div className="text-lg font-extrabold text-teal-700">{data.branch_tree.length}</div>
                </div>
            </div>

            {(section === 'all' || section === 'characters') && (
                <CharacterGraph nodes={data.character_graph.nodes} edges={data.character_graph.edges} />
            )}

            {(section === 'all' || section === 'timeline') && (
                <PitSwimlaneTimeline
                    projectId={projectId}
                    episodes={data.timeline.episodes}
                    arcs={data.timeline.arcs}
                    pits={data.timeline.pit_swimlanes}
                    storyBible={data.story_bible}
                />
            )}

            {(section === 'all' || section === 'branches') && (
                <BranchTreeGraph
                    projectId={projectId}
                    branches={data.branch_tree}
                    activeBranchId={data.branch_id}
                    onSelectBranch={(bid) => setBranchId(bid)}
                />
            )}

            {(section === 'all' || section === 'detective') && (
                <StoryDetectivePanel
                    projectId={projectId}
                    branchId={data.branch_id}
                    characters={data.character_graph.nodes}
                />
            )}
        </div>
    )
}
