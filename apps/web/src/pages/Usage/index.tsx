import UsagePanel from '@/components/UsagePanel'

export default function UsagePage() {
    return (
        <div className="space-y-6">
            <header className="pb-4 border-b border-[var(--border)] space-y-1">
                <h1 className="font-editorial text-2xl font-bold tracking-tight text-[var(--text-primary)] m-0">
                    模型用量与作图日志
                </h1>
                <p className="text-xs text-[var(--text-secondary)] m-0">
                    实时统计全部 LLM 对话、向量嵌入与图像生成调用的输入/输出 Token、Prompt 缓存读写命中率、模型分布与耗时。
                </p>
            </header>
            <UsagePanel />
        </div>
    )
}
