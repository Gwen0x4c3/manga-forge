import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Typography, Spin, Empty, Button, Select, TextArea, Steps, Toast, Tag, Collapse, Descriptions, Image } from '@douyinfe/semi-ui'
import { useQuery, useMutation } from '@tanstack/react-query'
import { episodeService, generationService } from '@/services/project'
import type { GenerationRun, GeneratedImage, ComposedPage } from '@/services/project'

const { Title, Paragraph } = Typography

export default function GenerationStudio() {
    const { episodeId } = useParams<{ projectId: string; episodeId: string }>()
    const navigate = useNavigate()
    const [tone, setTone] = useState('main')
    const [customInstructions, setCustomInstructions] = useState('')
    const [activeStep, setActiveStep] = useState(0)
    const [imageBackend, setImageBackend] = useState<string | undefined>(undefined)
    const [imageModel, setImageModel] = useState<string | undefined>(undefined)
    const [renderTriggered, setRenderTriggered] = useState(false)
    const [layoutTriggered, setLayoutTriggered] = useState(false)

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
        refetchInterval: activeStep === 1 || (activeStep === 3 && renderTriggered) || (activeStep === 4 && layoutTriggered) ? 3000 : false,
    })

    const { data: generatedImagesData } = useQuery({
        queryKey: ['generated-images', episodeId],
        queryFn: () => generationService.getGeneratedImages(episodeId!),
        enabled: !!episodeId && activeStep >= 3,
    })

    const { data: layoutResult } = useQuery({
        queryKey: ['layout-result', episodeId],
        queryFn: () => generationService.getLayoutResult(episodeId!),
        enabled: !!episodeId && activeStep >= 4,
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

    const renderMutation = useMutation({
        mutationFn: () => generationService.triggerRender({
            episode_id: episodeId!,
            storyboard_memory_id: storyboardMemory?.id,
            image_backend: imageBackend || undefined,
            image_model: imageModel || undefined,
        }),
        onSuccess: () => {
            Toast.success('Render started')
            setRenderTriggered(true)
        },
        onError: () => Toast.error('Failed to start render'),
    })

    const layoutMutation = useMutation({
        mutationFn: () => generationService.triggerLayout({
            episode_id: episodeId!,
        }),
        onSuccess: () => {
            Toast.success('Layout composition started')
            setLayoutTriggered(true)
        },
        onError: () => Toast.error('Failed to start layout'),
    })

    if (episodeLoading) return <Spin size="large" />
    if (!episode) return <Empty description="Episode not found" />

    const storyboardMemory = memories?.find((m: { type: string }) => m.type === 'storyboard_json')
    const scriptRuns = runs?.items?.filter((r: GenerationRun) => r.stage === 'script') || []
    const renderRuns = runs?.items?.filter((r: GenerationRun) => r.stage === 'render') || []
    const layoutRuns = runs?.items?.filter((r: GenerationRun) => r.stage === 'layout') || []
    const latestScriptRun = scriptRuns[0]
    const latestRenderRun = renderRuns[0]
    const latestLayoutRun = layoutRuns[0]

    const generatedImages: GeneratedImage[] = generatedImagesData?.items || []
    const composedPages: ComposedPage[] = layoutResult?.pages || []

    const renderSucceeded = latestRenderRun?.status === 'succeeded'
    const layoutSucceeded = latestLayoutRun?.status === 'succeeded'

    return (
        <div>
            <div className="mb-6 flex items-center gap-3">
                <Button onClick={() => navigate(-1)}>← Back</Button>
                <Title heading={4}>Generation Studio - Episode {episode.number}</Title>
            </div>

            <Steps current={activeStep} className="mb-8">
                <Steps.Step title="Configure" description="Set generation parameters" />
                <Steps.Step title="Script Generating" description="LLM is creating storyboard" />
                <Steps.Step title="Script Review" description="Review generated script" />
                <Steps.Step title="Render" description="Generate panel images" />
                <Steps.Step title="Layout & Export" description="Compose final pages" />
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
                    {latestScriptRun && (
                        <div className="mt-4">
                            <Tag color={latestScriptRun.status === 'running' ? 'blue' : latestScriptRun.status === 'succeeded' ? 'green' : 'red'}>
                                {latestScriptRun.status}
                            </Tag>
                            <Button className="ml-2" onClick={() => {
                                if (latestScriptRun.status === 'succeeded') setActiveStep(2)
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
                        <Button
                            theme="solid"
                            onClick={() => setActiveStep(3)}
                        >
                            Render Images
                        </Button>
                    </div>
                </div>
            )}

            {activeStep === 3 && (
                <div className="max-w-4xl">
                    <Title heading={5}>Render Panel Images</Title>

                    {!renderTriggered && !renderSucceeded && (
                        <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-medium mb-1">Image Backend (optional)</label>
                                    <Select
                                        value={imageBackend}
                                        onChange={(v: string | string[] | undefined) => setImageBackend(v ? String(v) : undefined)}
                                        style={{ width: '100%' }}
                                        placeholder="Default"
                                    >
                                        <Select.Option value="openai">OpenAI</Select.Option>
                                        <Select.Option value="custom">Custom HTTP</Select.Option>
                                        <Select.Option value="mock">Mock</Select.Option>
                                    </Select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium mb-1">Image Model (optional)</label>
                                    <Select
                                        value={imageModel}
                                        onChange={(v: string | string[] | undefined) => setImageModel(v ? String(v) : undefined)}
                                        style={{ width: '100%' }}
                                        placeholder="Default"
                                    >
                                        <Select.Option value="gpt-image-2">GPT-Image-2</Select.Option>
                                        <Select.Option value="dall-e-3">DALL-E 3</Select.Option>
                                    </Select>
                                </div>
                            </div>
                            <Button
                                theme="solid"
                                size="large"
                                loading={renderMutation.isPending}
                                onClick={() => renderMutation.mutate()}
                            >
                                Render Images
                            </Button>
                        </div>
                    )}

                    {renderTriggered && !renderSucceeded && (
                        <div className="text-center py-12">
                            <Spin size="large" />
                            <Paragraph className="mt-4">Rendering panel images...</Paragraph>
                            {latestRenderRun && (
                                <div className="mt-4">
                                    <Tag color={latestRenderRun.status === 'running' ? 'blue' : latestRenderRun.status === 'succeeded' ? 'green' : 'red'}>
                                        {latestRenderRun.status}
                                    </Tag>
                                    {latestRenderRun.status === 'failed' && (
                                        <Paragraph type="danger" className="mt-2">{latestRenderRun.error || 'Render failed'}</Paragraph>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {renderSucceeded && generatedImages.length > 0 && (
                        <div>
                            <div className="mb-4">
                                <Tag color="green" size="large">Render Complete - {generatedImages.length} images</Tag>
                            </div>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                                {generatedImages.map((img) => (
                                    <div key={img.id} className="border rounded p-2">
                                        <Image
                                            src={`/api/v1/storage/mangaforge/${img.image_path}`}
                                            alt={`Panel ${img.panel_id || img.id}`}
                                            className="w-full"
                                        />
                                        <div className="text-xs text-gray-500 mt-1 text-center">
                                            {img.panel_id ? `Panel ${img.panel_id}` : img.id}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="mt-6 flex gap-2">
                                <Button onClick={() => { setRenderTriggered(false); setActiveStep(2) }}>
                                    Back to Script
                                </Button>
                                <Button
                                    theme="solid"
                                    size="large"
                                    onClick={() => setActiveStep(4)}
                                >
                                    Layout & Export
                                </Button>
                            </div>
                        </div>
                    )}

                    {renderSucceeded && generatedImages.length === 0 && (
                        <div className="text-center py-8">
                            <Paragraph>Render completed but no images found. Try refreshing.</Paragraph>
                        </div>
                    )}
                </div>
            )}

            {activeStep === 4 && (
                <div className="max-w-4xl">
                    <Title heading={5}>Layout & Export</Title>

                    {!layoutTriggered && !layoutSucceeded && (
                        <div className="space-y-4">
                            <Paragraph>Compose rendered panel images into final manga pages.</Paragraph>
                            <Button
                                theme="solid"
                                size="large"
                                loading={layoutMutation.isPending}
                                onClick={() => layoutMutation.mutate()}
                            >
                                Compose Pages
                            </Button>
                        </div>
                    )}

                    {layoutTriggered && !layoutSucceeded && (
                        <div className="text-center py-12">
                            <Spin size="large" />
                            <Paragraph className="mt-4">Composing page layouts...</Paragraph>
                            {latestLayoutRun && (
                                <div className="mt-4">
                                    <Tag color={latestLayoutRun.status === 'running' ? 'blue' : latestLayoutRun.status === 'succeeded' ? 'green' : 'red'}>
                                        {latestLayoutRun.status}
                                    </Tag>
                                    {latestLayoutRun.status === 'failed' && (
                                        <Paragraph type="danger" className="mt-2">{latestLayoutRun.error || 'Layout failed'}</Paragraph>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {layoutSucceeded && composedPages.length > 0 && (
                        <div>
                            <div className="mb-4">
                                <Tag color="green" size="large">Layout Complete - {composedPages.length} pages</Tag>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                {composedPages.map((page) => (
                                    <div key={page.page_number} className="border rounded p-3">
                                        <div className="text-sm font-medium mb-2">
                                            Page {page.page_number} <Tag size="small">{page.layout}</Tag>
                                        </div>
                                        <Image
                                            src={`/api/v1/storage/mangaforge/${page.image_path}`}
                                            alt={`Page ${page.page_number}`}
                                            className="w-full"
                                        />
                                    </div>
                                ))}
                            </div>
                            <div className="mt-6 flex gap-2">
                                <Button onClick={() => { setLayoutTriggered(false); setActiveStep(3) }}>
                                    Back to Render
                                </Button>
                                <Button
                                    theme="solid"
                                    onClick={() => { setLayoutTriggered(false); setRenderTriggered(false); setActiveStep(0) }}
                                >
                                    Start Over
                                </Button>
                            </div>
                        </div>
                    )}

                    {layoutSucceeded && composedPages.length === 0 && (
                        <div className="text-center py-8">
                            <Paragraph>Layout completed but no pages found. Try refreshing.</Paragraph>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
