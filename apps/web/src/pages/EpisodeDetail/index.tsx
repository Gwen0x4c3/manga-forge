import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Typography, Spin, Empty, Tag, Image, Tabs, TabPane, Button, Descriptions, Collapse, Toast, Modal, Select, TextArea } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconBolt, IconForward } from '@douyinfe/semi-icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { episodeService, generationService } from '@/services/project'
import type { EpisodeMemory } from '@/services/project'

const { Title, Paragraph } = Typography

const STATUS_COLORS: Record<string, TagColor> = {
    imported: 'blue',
    understood: 'cyan',
    scripted: 'green',
    rendered: 'orange',
    published: 'purple',
    draft: 'grey',
    generating: 'violet',
}

const CATEGORY_LABELS: Record<string, { text: string; color: TagColor }> = {
    regular: { text: '正篇', color: 'blue' },
    special: { text: '番外', color: 'orange' },
    extra: { text: '加笔', color: 'purple' },
}

export default function EpisodeDetail() {
    const { projectId, episodeId } = useParams<{ projectId: string; episodeId: string }>()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [showContinue, setShowContinue] = useState(false)
    const [continueTone, setContinueTone] = useState('main')
    const [continueInstructions, setContinueInstructions] = useState('')

    const { data: episode, isLoading: episodeLoading } = useQuery({
        queryKey: ['episode', episodeId],
        queryFn: () => episodeService.get(episodeId!),
        enabled: !!episodeId,
    })

    const { data: pages, isLoading: pagesLoading } = useQuery({
        queryKey: ['episode-pages', episodeId],
        queryFn: () => episodeService.getPages(episodeId!),
        enabled: !!episodeId,
    })

    const { data: memories, isLoading: memoriesLoading } = useQuery({
        queryKey: ['episode-memories', episodeId],
        queryFn: () => episodeService.getMemories(episodeId!),
        enabled: !!episodeId,
    })

    const { data: generatedImages, isLoading: imagesLoading } = useQuery({
        queryKey: ['generated-images', episodeId],
        queryFn: () => generationService.getGeneratedImages(episodeId!),
        enabled: !!episodeId,
    })

    const { data: layoutResult, isLoading: layoutLoading } = useQuery({
        queryKey: ['layout-result', episodeId],
        queryFn: () => generationService.getLayoutResult(episodeId!),
        enabled: !!episodeId,
    })

    const understandMutation = useMutation({
        mutationFn: () => generationService.triggerUnderstand(episodeId!),
        onSuccess: () => {
            Toast.success('Understanding task started')
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
        },
        onError: () => {},
    })

    const renderMutation = useMutation({
        mutationFn: () => generationService.triggerRender({ episode_id: episodeId! }),
        onSuccess: () => {
            Toast.success('Render task started')
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
        },
        onError: () => {},
    })

    const layoutMutation = useMutation({
        mutationFn: () => generationService.triggerLayout({ episode_id: episodeId! }),
        onSuccess: () => {
            Toast.success('Layout task started')
            queryClient.invalidateQueries({ queryKey: ['episode', episodeId] })
        },
        onError: () => {},
    })

    const continueMutation = useMutation({
        mutationFn: () => generationService.triggerContinue({
            project_id: projectId!,
            branch_id: episode?.branch_id || '',
            base_episode_number: episode?.number || 1,
            tone: continueTone,
            custom_instructions: continueInstructions || undefined,
        }),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['episodes', projectId] })
            setShowContinue(false)
            Toast.success('Continue generation started')
            navigate(`/projects/${projectId}/episodes/${data.episode_id}/generate`)
        },
        onError: () => {},
    })

    if (episodeLoading) return <Spin size="large" />
    if (!episode) return <Empty description="Episode not found" />

    const summaryMemory = memories?.find((m: EpisodeMemory) => m.type === 'summary')
    const eventsMemory = memories?.find((m: EpisodeMemory) => m.type === 'events')
    const stateMemory = memories?.find((m: EpisodeMemory) => m.type === 'state_snapshot')
    const storyboardMemory = memories?.find((m: EpisodeMemory) => m.type === 'storyboard_json')
    const writebackMemories = memories?.filter((m: EpisodeMemory) => m.type === 'writeback') || []

    return (
        <div>
            <div className="mb-6 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Title heading={3}>{episode.label}</Title>
                    <Tag color={STATUS_COLORS[episode.status] || ('default' as TagColor)}>{episode.status}</Tag>
                    {episode.title && <Paragraph>{episode.title}</Paragraph>}
                </div>
                <div className="flex gap-2">
                    {episode.status === 'imported' && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            loading={understandMutation.isPending}
                            onClick={() => understandMutation.mutate()}
                        >
                            Understand
                        </Button>
                    )}
                    {(episode.status === 'understood' || episode.status === 'scripted') && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            onClick={() => navigate(`/projects/${projectId}/episodes/${episodeId}/generate`)}
                        >
                            Generate Script
                        </Button>
                    )}
                    {episode.status === 'scripted' && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            loading={renderMutation.isPending}
                            onClick={() => renderMutation.mutate()}
                        >
                            Render Images
                        </Button>
                    )}
                    {episode.status === 'rendered' && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            disabled
                        >
                            Render Images
                        </Button>
                    )}
                    {episode.status === 'rendered' && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            loading={layoutMutation.isPending}
                            onClick={() => layoutMutation.mutate()}
                        >
                            Layout & Export
                        </Button>
                    )}
                    {episode.status === 'published' && (
                        <Button
                            icon={<IconBolt />}
                            theme="solid"
                            onClick={() => navigate(`/projects/${projectId}/studio`)}
                        >
                            View in Studio
                        </Button>
                    )}
                    {(episode.status === 'published' || episode.status === 'understood') && (
                        <Button
                            icon={<IconForward />}
                            onClick={() => setShowContinue(true)}
                        >
                            Continue from Here
                        </Button>
                    )}
                </div>
            </div>

            <Tabs>
                <TabPane tab="Pages" itemKey="pages">
                    {pagesLoading && <Spin />}
                    {!pagesLoading && (!pages || pages.length === 0) && (
                        <Empty description="No pages uploaded yet" />
                    )}
                    {!pagesLoading && pages && pages.length > 0 && (
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                            {pages.map((page) => (
                                <div key={page.id} className="border rounded p-2">
                                    <div className="w-full h-80 overflow-hidden flex items-center justify-center bg-gray-50">
                                        <img
                                            src={`/api/v1/storage/mangaforge/${page.image_path}`}
                                            alt={`Page ${page.page_index + 1}`}
                                            className="max-w-full max-h-full object-contain"
                                        />
                                    </div>
                                    <div className="text-center text-sm text-gray-500 mt-1">
                                        Page {page.page_index + 1}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Summary" itemKey="summary">
                    {memoriesLoading && <Spin />}
                    {!memoriesLoading && !summaryMemory && (
                        <Empty description="No summary yet. Click 'Understand' to generate." />
                    )}
                    {!memoriesLoading && summaryMemory && (
                        <div className="max-w-3xl">
                            <Paragraph>{typeof summaryMemory.content === 'object'
                                ? (summaryMemory.content as Record<string, unknown>).summary as string || JSON.stringify(summaryMemory.content, null, 2)
                                : String(summaryMemory.content)}</Paragraph>
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Events" itemKey="events">
                    {memoriesLoading && <Spin />}
                    {!memoriesLoading && !eventsMemory && (
                        <Empty description="No events extracted yet" />
                    )}
                    {!memoriesLoading && eventsMemory && (
                        <div className="max-w-3xl space-y-2">
                            {Array.isArray((eventsMemory.content as Record<string, unknown>)?.data)
                                ? ((eventsMemory.content as Record<string, unknown>).data as Array<Record<string, unknown>>).map((event, i) => (
                                    <div key={i} className="border rounded p-3">
                                        <div className="font-medium">{String(event.description || JSON.stringify(event))}</div>
                                        {event.characters_involved && Array.isArray(event.characters_involved) ? (
                                            <div className="mt-1 flex gap-1">
                                                {(event.characters_involved as string[]).map((c: string, j: number) => (
                                                    <Tag key={j} size="small">{c}</Tag>
                                                ))}
                                            </div>
                                        ) : null}
                                    </div>
                                ))
                                : <pre className="text-sm bg-gray-50 p-3 rounded">{JSON.stringify(eventsMemory.content, null, 2)}</pre>
                            }
                        </div>
                    )}
                </TabPane>

                <TabPane tab="State Changes" itemKey="state">
                    {memoriesLoading && <Spin />}
                    {!memoriesLoading && !stateMemory && (
                        <Empty description="No state changes recorded yet" />
                    )}
                    {!memoriesLoading && stateMemory && (
                        <div className="max-w-3xl space-y-2">
                            {Array.isArray((stateMemory.content as Record<string, unknown>)?.data)
                                ? ((stateMemory.content as Record<string, unknown>).data as Array<Record<string, unknown>>).map((change, i) => (
                                    <div key={i} className="border rounded p-3 flex items-center gap-3">
                                        <Tag color="blue">{String(change.character || '')}</Tag>
                                        <span className="text-gray-500">{String(change.attribute || '')}</span>
                                        <span>{String(change.before || '?')}</span>
                                        <span className="text-gray-400">→</span>
                                        <span className="font-medium">{String(change.after || '')}</span>
                                    </div>
                                ))
                                : <pre className="text-sm bg-gray-50 p-3 rounded">{JSON.stringify(stateMemory.content, null, 2)}</pre>
                            }
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Storyboard" itemKey="storyboard">
                    {memoriesLoading && <Spin />}
                    {!memoriesLoading && !storyboardMemory && (
                        <Empty description="No storyboard generated yet. Click 'Generate Script' to create one." />
                    )}
                    {!memoriesLoading && storyboardMemory && (
                        <div className="max-w-4xl">
                            <Descriptions
                                data={[
                                    { key: 'Title', value: String((storyboardMemory.content as Record<string, unknown>)?.title || '') },
                                    { key: 'Tone', value: String((storyboardMemory.content as Record<string, unknown>)?.tone || '') },
                                    { key: 'Synopsis', value: String((storyboardMemory.content as Record<string, unknown>)?.synopsis || '') },
                                ]}
                            />
                            <Title heading={5} className="mt-4">Pages</Title>
                            <Collapse>
                                {Array.isArray((storyboardMemory.content as Record<string, unknown>)?.pages)
                                    ? ((storyboardMemory.content as Record<string, unknown>).pages as Array<Record<string, unknown>>).map((page, i) => (
                                        <Collapse.Panel header={`Page ${page.page_number || i + 1} (${page.layout || '2x2'})`} itemKey={String(i)} key={i}>
                                            {Array.isArray(page.panels) && (page.panels as Array<Record<string, unknown>>).map((panel, j) => (
                                                <div key={j} className="border-l-2 border-blue-300 pl-3 mb-3">
                                                    <div className="font-medium text-sm">Panel {String(panel.panel_id || j + 1)}</div>
                                                    <div className="text-sm text-gray-600">{String(panel.scene || '')}</div>
                                                    {Array.isArray(panel.dialogue) && (panel.dialogue as Array<Record<string, unknown>>).map((d, k) => (
                                                        <div key={k} className="text-sm ml-2">
                                                            <Tag size="small">{String(d.speaker || '')}</Tag> {String(d.text || '')}
                                                        </div>
                                                    ))}
                                                    <div className="text-xs text-gray-400 mt-1">Prompt: {String(panel.prompt || '')}</div>
                                                </div>
                                            ))}
                                        </Collapse.Panel>
                                    ))
                                    : <pre className="text-sm bg-gray-50 p-3 rounded">{JSON.stringify(storyboardMemory.content, null, 2)}</pre>
                                }
                            </Collapse>
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Writeback" itemKey="writeback">
                    {memoriesLoading && <Spin />}
                    {!memoriesLoading && writebackMemories.length === 0 && (
                        <Empty description="No writeback data yet. Writeback runs automatically after layout." />
                    )}
                    {!memoriesLoading && writebackMemories.length > 0 && (
                        <div className="max-w-4xl space-y-4">
                            {writebackMemories.map((wb, i) => (
                                <div key={wb.id} className="border rounded p-4">
                                    <div className="flex items-center gap-2 mb-2">
                                        <Tag color="violet">Writeback</Tag>
                                        <span className="text-sm text-gray-500">{new Date(wb.created_at).toLocaleString()}</span>
                                    </div>
                                    <pre className="text-sm bg-gray-50 p-3 rounded overflow-auto max-h-96">
                                        {JSON.stringify(wb.content, null, 2)}
                                    </pre>
                                </div>
                            ))}
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Generated Images" itemKey="generated">
                    {imagesLoading && <Spin />}
                    {!imagesLoading && (!generatedImages?.items || generatedImages.items.length === 0) && (
                        <Empty description="No rendered images yet. Generate script first, then render." />
                    )}
                    {!imagesLoading && generatedImages?.items && generatedImages.items.length > 0 && (
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                            {generatedImages?.items && generatedImages.items.map((img) => (
                                <div key={img.id} className="border rounded p-2">
                                    <div className="w-full h-80 overflow-hidden flex items-center justify-center bg-gray-50">
                                        <img
                                            src={`/api/v1/storage/mangaforge/${img.image_path}`}
                                            alt={img.panel_id || ''}
                                            className="max-w-full max-h-full object-contain"
                                        />
                                    </div>
                                    <div className="text-center text-sm text-gray-500 mt-1">
                                        {img.panel_id || 'Unknown'}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </TabPane>

                <TabPane tab="Final Pages" itemKey="layout">
                    {layoutLoading && <Spin />}
                    {!layoutLoading && (!layoutResult?.pages || layoutResult.pages.length === 0) && (
                        <Empty description="No composed pages yet. Render images first, then layout." />
                    )}
                    {!layoutLoading && layoutResult?.pages && layoutResult.pages.length > 0 && (
                        <div className="space-y-4">
                            {layoutResult.pages.map((page) => (
                                <div key={page.page_number} className="border rounded p-4">
                                    <div className="flex items-center gap-3 mb-2">
                                        <span className="font-medium">Page {page.page_number}</span>
                                        <Tag>{page.layout}</Tag>
                                    </div>
                                    <div className="w-full max-w-2xl h-96 overflow-hidden flex items-center justify-center bg-gray-50">
                                        <img
                                            src={`/api/v1/storage/mangaforge/${page.image_path}`}
                                            alt={`Page ${page.page_number}`}
                                            className="max-w-full max-h-full object-contain"
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </TabPane>
            </Tabs>

            <Modal
                title="Continue from Here"
                visible={showContinue}
                onCancel={() => setShowContinue(false)}
                footer={null}
                width={480}
            >
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Tone</label>
                        <Select
                            value={continueTone}
                            onChange={(v: string | string[] | undefined) => setContinueTone(String(v || 'main'))}
                            style={{ width: '100%' }}
                        >
                            <Select.Option value="main">Main Plot</Select.Option>
                            <Select.Option value="daily">Daily / Slice of Life</Select.Option>
                            <Select.Option value="climax">Climax</Select.Option>
                            <Select.Option value="filler">Filler</Select.Option>
                            <Select.Option value="pit_resolve">Resolve Foreshadowing</Select.Option>
                        </Select>
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Custom Instructions (optional)</label>
                        <TextArea
                            value={continueInstructions}
                            onChange={(v: string) => setContinueInstructions(v)}
                            placeholder="Any specific requirements for the next episode..."
                            rows={3}
                        />
                    </div>
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => setShowContinue(false)}>Cancel</Button>
                        <Button
                            theme="solid"
                            icon={<IconForward />}
                            loading={continueMutation.isPending}
                            onClick={() => continueMutation.mutate()}
                        >
                            Continue Generation
                        </Button>
                    </div>
                </div>
            </Modal>
        </div>
    )
}
