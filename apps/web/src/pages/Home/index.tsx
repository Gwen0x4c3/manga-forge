import { Typography } from '@douyinfe/semi-ui'

const { Title, Paragraph } = Typography

export default function HomePage() {
    return (
        <div className="flex flex-col items-center justify-center h-full">
            <Title heading={2}>Welcome to MangaForge</Title>
            <Paragraph>AI-powered manga continuation system</Paragraph>
        </div>
    )
}
