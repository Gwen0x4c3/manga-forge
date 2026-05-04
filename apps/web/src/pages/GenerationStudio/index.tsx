import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Typography, Spin, Empty, Button, Select, TextArea, Steps, Toast, Tag, Collapse, Descriptions } from '@douyinfe/semi-ui'
import { useQuery, useMutation } from '@tanstack/react-query'
import { episodeService, generationService } from '@/services/project'
import type { GenerationRun } from '@/services/project'

const { Title, Paragraph } = Typography

export default function GenerationStudio() {
    const { episodeId } = useParams<{ projectId: string; episodeId: string }>()
    const navigate = useNavigate()
    const [tone, setTone] = useState('main')
    const [customInstructions, setCustomInstructions] = useState('')
    const [activeStep, setActiveStep] = useState(0)

    const { data: episode, isLoading: episodeLoading } = useQuery({
        queryKey: ['episode', episodeId],
        queryFn: () => episodeService.get(episodeId!),
        enabled: !!episodeId,
    })

    const { data: memories } = useQuery({
        queryKey: ['episode-memories', episodeId],
        queryFn: () => episodeService.getMemories(episodeId!),
        enabled: !!episodeId,
    })

    const { data: runs } = useQuery({
        queryKey: ['generation-runs', episodeId],
        queryFn: () => generationService.listEpisodeRuns(episodeId!),
        enabled: !!episodeId,
    })

    const scriptMutation = useMutation({
        mutationFn: () => generationService.triggerScriptGeneration({
            episode_id: episodeId!,
            branch_id: episode?.branch_id || '',
            base_episode_number: (episode?.number || 1) - 1,
            tone,
            custom_instructions: customInstructions || undefined,
        }),
        onSuccess: () => {
            Toast.success('Script generation started')
            setActiveStep(1)
        },
        onError: () => Toast.error('Failed to start script generation'),
    })

    if (episodeLoading) return <Spin size="large" />
    if (!episode) return <Empty description="Episode not found" />

    const storyboardMemory = memories?.find((m: { type: string }) => m.type === 'storyboard_json')
    const scriptRuns = runs?.items?.filter((r: GenerationRun) => r.stage === 'script') || []
    const latestRun = scriptRuns[0]

    return (
        <div>
            <div className="mb-6 flex items-center gap-3">
                <Button onClick={() => navigate(-1)}>← Back</Button>
                <Title heading={4}>Generation Studio - Episode {episode.number}</Title>
            </div>

            <Steps current={activeStep} className="mb-8">
                <Steps.Step title="Configure" description="Set generation parameters" />
                <Steps.Step title="Generating" description="LLM is creating storyboard" />
                <Steps.Step title="Review" description="Review generated script" />
            </Steps>

            {activeStep === 0 && (
                <div className="max-w-2xl space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Tone</label>
                        <Select value={tone} onChange={(v: string | string[] | undefined) => setTone(String(v || 'main'))} style={{ width: '100%' }}>
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
                            value={customInstructions}
                            onChange={setCustomInstructions}
                            placeholder="Any specific requirements for this episode..."
                            rows={4}
                        />
                    </div>
                    <Button
                        theme="solid"
                        size="large"
                        loading={scriptMutation.isPending}
                        onClick={() => scriptMutation.mutate()}
                    >
                        Generate Script
                    </Button>
                </div>
            )}

            {activeStep === 1 && (
                <div className="text-center py-12">
                    <Spin size="large" />
                    <Paragraph className="mt-4">Generating storyboard script...</Paragraph>
                    {latestRun && (
                        <div className="mt-4">
                            <Tag color={latestRun.status === 'running' ? 'blue' : latestRun.status === 'succeeded' ? 'green' : 'red'}>
                                {latestRun.status}
                            </Tag>
                            <Button className="ml-2" onClick={() => {
                                if (latestRun.status === 'succeeded') setActiveStep(2)
                            }}>
                                Check Status
                            </Button>
                        </div>
                    )}
                </div>
            )}

            {activeStep === 2 && storyboardMemory && (
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
                                            {Array.isArray(panel.characters) && (panel.characters as Array<Record<string, unknown>>).map((c, k) => (
                                                <Tag key={k} size="small" className="mr-1">{String(c.name || '')}</Tag>
                                            ))}
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
                    <div className="mt-4 flex gap-2">
                        <Button onClick={() => setActiveStep(0)}>Regenerate</Button>
                    </div>
                </div>
            )}
        </div>
    )
}
