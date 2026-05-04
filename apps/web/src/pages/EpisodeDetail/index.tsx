import { useParams } from 'react-router-dom'
import { Typography, Spin, Empty, Tag, Image } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { useQuery } from '@tanstack/react-query'
import { episodeService } from '@/services/project'

const { Title, Paragraph } = Typography

const STATUS_COLORS: Record<string, TagColor> = {
    imported: 'blue',
    understood: 'cyan',
    scripted: 'green',
    rendered: 'orange',
    published: 'purple',
}

export default function EpisodeDetail() {
    const { episodeId } = useParams<{ episodeId: string }>()

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

    if (episodeLoading) return <Spin size="large" />
    if (!episode) return <Empty description="Episode not found" />

    return (
        <div>
            <div className="mb-6">
                <div className="flex items-center gap-3">
                    <Title heading={3}>Episode {episode.number}</Title>
                    <Tag color={STATUS_COLORS[episode.status] || 'default'}>{episode.status}</Tag>
                </div>
                {episode.title && <Paragraph>{episode.title}</Paragraph>}
            </div>

            <Title heading={5}>Pages</Title>
            {pagesLoading && <Spin />}
            {!pagesLoading && (!pages || pages.length === 0) && (
                <Empty description="No pages uploaded yet" />
            )}
            {!pagesLoading && pages && pages.length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                    {pages.map((page) => (
                        <div key={page.id} className="border rounded p-2">
                            <Image
                                src={`/api/v1/storage/mangaforge/${page.image_path}`}
                                alt={`Page ${page.page_index + 1}`}
                                className="w-full"
                            />
                            <div className="text-center text-sm text-gray-500 mt-1">
                                Page {page.page_index + 1}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
