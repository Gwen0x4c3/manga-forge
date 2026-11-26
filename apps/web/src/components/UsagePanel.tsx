import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button, Empty, Select, Spin, Table, Tag, Tooltip } from '@douyinfe/semi-ui'
import { IconRefresh } from '@douyinfe/semi-icons'
import { usageService } from '@/services/project'
import type { UsageByModelItem, UsageRecordItem } from '@/services/project'

interface Props {
    projectId?: string
    episodeId?: string
}

const OP_LABELS: Record<string, string> = {
    understand: '多模态剧情理解',
    script: '分镜剧本生成',
    script_retry: '分镜审校重写',
    consistency_check: '连续性审校',
    story_qa: '剧情侦探 QA',
    render_plan: 'Render Agent 调度',
    summarize_compress: '长程摘要压缩',
    embedding: '向量嵌入',
    image_generate: '分格作图',
    image_inpaint: '局部重绘',
    llm_chat: 'LLM 对话',
}

const KIND_LABELS: Record<string, { label: string; color: 'blue' | 'orange' | 'grey' }> = {
    llm: { label: 'LLM', color: 'blue' },
    image: { label: '作图', color: 'orange' },
    embedding: { label: 'Embedding', color: 'grey' },
}

export function formatTokens(n: number): string {
    if (!n) return '0'
    if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)} B`
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)} K`
    return String(n)
}

export function formatDuration(ms: number): string {
    if (!ms) return '0 ms'
    if (ms < 1000) return `${ms} ms`
    if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
    const mins = Math.floor(ms / 60_000)
    const secs = ((ms % 60_000) / 1000).toFixed(1)
    return `${mins}m ${secs}s`
}

export default function UsagePanel({ projectId, episodeId }: Props) {
    const navigate = useNavigate()
    const [days, setDays] = useState<number | undefined>(undefined)
    const [kindFilter, setKindFilter] = useState<string | undefined>(undefined)
    const [modelFilter, setModelFilter] = useState<string | undefined>(undefined)
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(30)

    const {
        data: summary,
        isLoading: summaryLoading,
        refetch: refetchSummary,
        isFetching: summaryFetching,
    } = useQuery({
        queryKey: ['usage-summary', projectId, episodeId, days],
        queryFn: () => usageService.summary({ project_id: projectId, episode_id: episodeId, days }),
    })

    const {
        data: recordsData,
        isLoading: recordsLoading,
        refetch: refetchRecords,
        isFetching: recordsFetching,
    } = useQuery({
        queryKey: ['usage-records', projectId, episodeId, kindFilter, modelFilter, page, pageSize],
        queryFn: () =>
            usageService.records({
                project_id: projectId,
                episode_id: episodeId,
                kind: kindFilter,
                model: modelFilter,
                page,
                page_size: pageSize,
            }),
    })

    const totals = summary?.totals
    const byModel = summary?.by_model || []
    const daily = summary?.daily || []
    const records = recordsData?.items || []
    const maxDailyTokens = Math.max(1, ...daily.map((d) => d.total_tokens))

    const modelOptions = Array.from(new Set(byModel.map((m) => m.model)))

    const modelColumns = [
        {
            title: '模型',
            dataIndex: 'model',
            key: 'model',
            render: (m: string, r: UsageByModelItem) => (
                <div className="space-y-0.5">
                    <div className="font-mono text-xs font-semibold text-[var(--text-primary)]">{m}</div>
                    <div className="text-[10px] font-mono text-[var(--text-muted)]">{r.provider}</div>
                </div>
            ),
        },
        {
            title: '类型',
            dataIndex: 'kind',
            key: 'kind',
            width: 96,
            render: (k: string) => {
                const meta = KIND_LABELS[k] || { label: k, color: 'grey' as const }
                return (
                    <Tag size="small" color={meta.color}>
                        {meta.label}
                    </Tag>
                )
            },
        },
        {
            title: '调用数',
            dataIndex: 'calls',
            key: 'calls',
            width: 90,
            render: (c: number, r: UsageByModelItem) => (
                <span className="font-mono text-xs text-[var(--text-primary)]">
                    {c}
                    {r.failed_calls > 0 && (
                        <span className="text-[var(--accent)] ml-1">({r.failed_calls} 失败)</span>
                    )}
                </span>
            ),
        },
        {
            title: '输入 Token',
            dataIndex: 'input_tokens',
            key: 'input_tokens',
            width: 115,
            render: (v: number) => (
                <Tooltip content={v.toLocaleString()}>
                    <span className="font-mono text-xs text-[var(--text-primary)]">{formatTokens(v)}</span>
                </Tooltip>
            ),
        },
        {
            title: '输出 Token',
            dataIndex: 'output_tokens',
            key: 'output_tokens',
            width: 115,
            render: (v: number) => (
                <Tooltip content={v.toLocaleString()}>
                    <span className="font-mono text-xs text-[var(--text-primary)]">{formatTokens(v)}</span>
                </Tooltip>
            ),
        },
        {
            title: '缓存读 / 写',
            key: 'cache',
            width: 155,
            render: (_: unknown, r: UsageByModelItem) =>
                r.kind === 'image' ? (
                    <span className="text-xs text-[var(--text-muted)]">-</span>
                ) : (
                    <Tooltip
                        content={`读: ${r.cache_read_tokens.toLocaleString()} / 写: ${r.cache_write_tokens.toLocaleString()}`}
                    >
                        <span className="font-mono text-xs text-[var(--text-secondary)]">
                            {formatTokens(r.cache_read_tokens)} / {formatTokens(r.cache_write_tokens)}
                        </span>
                    </Tooltip>
                ),
        },
        {
            title: '缓存率',
            dataIndex: 'cache_hit_rate',
            key: 'cache_hit_rate',
            width: 92,
            render: (rate: number, r: UsageByModelItem) =>
                r.kind === 'image' ? (
                    <span className="text-xs text-[var(--text-muted)]">-</span>
                ) : (
                    <span
                        className="font-mono text-xs font-semibold"
                        style={{ color: rate >= 40 ? 'var(--status-ok)' : 'var(--text-secondary)' }}
                    >
                        {rate.toFixed(1)}%
                    </span>
                ),
        },
        {
            title: '出图数',
            dataIndex: 'image_count',
            key: 'image_count',
            width: 84,
            render: (n: number) => (
                <span className="font-mono text-xs text-[var(--text-primary)]">{n > 0 ? `${n} 张` : '-'}</span>
            ),
        },
        {
            title: '平均耗时',
            dataIndex: 'avg_duration_ms',
            key: 'avg_duration_ms',
            width: 100,
            render: (ms: number) => (
                <span className="font-mono text-xs text-[var(--text-secondary)]">{formatDuration(ms)}</span>
            ),
        },
    ]

    const recordColumns = [
        {
            title: '时间',
            dataIndex: 'created_at',
            key: 'created_at',
            width: 148,
            render: (ts: string) => (
                <span className="font-mono text-[11px] text-[var(--text-muted)]">
                    {new Date(ts).toLocaleString()}
                </span>
            ),
        },
        {
            title: '类型 / 阶段',
            key: 'op',
            width: 170,
            render: (_: unknown, r: UsageRecordItem) => {
                const meta = KIND_LABELS[r.kind] || { label: r.kind, color: 'grey' as const }
                return (
                    <div className="flex items-center gap-1.5 flex-wrap">
                        <Tag size="small" color={meta.color}>
                            {meta.label}
                        </Tag>
                        <span className="text-xs text-[var(--text-primary)]">
                            {OP_LABELS[r.operation] || r.operation}
                        </span>
                    </div>
                )
            },
        },
        {
            title: '模型',
            dataIndex: 'model',
            key: 'model',
            width: 180,
            render: (m: string, r: UsageRecordItem) => (
                <div className="min-w-0">
                    <div className="font-mono text-xs text-[var(--text-primary)] truncate" title={m}>
                        {m}
                    </div>
                    <div className="text-[10px] font-mono text-[var(--text-muted)]">{r.provider}</div>
                </div>
            ),
        },
        ...(!projectId
            ? [
                  {
                      title: '所属作品 / 章节',
                      key: 'scope',
                      width: 180,
                      render: (_: unknown, r: UsageRecordItem) =>
                          r.project_id ? (
                              <button
                                  type="button"
                                  onClick={() =>
                                      navigate(
                                          r.episode_id
                                              ? `/projects/${r.project_id}/episodes/${r.episode_id}`
                                              : `/projects/${r.project_id}?view=episodes`,
                                      )
                                  }
                                  className="text-left bg-transparent border-0 p-0 cursor-pointer text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] truncate max-w-[170px]"
                              >
                                  {r.project_title || r.project_id.slice(0, 8)}
                                  {r.episode_label ? ` · 第${r.episode_label}话` : ''}
                              </button>
                          ) : (
                              <span className="text-xs text-[var(--text-muted)]">-</span>
                          ),
                  },
              ]
            : [
                  {
                      title: '章节 / 分格',
                      key: 'ep',
                      width: 120,
                      render: (_: unknown, r: UsageRecordItem) => {
                          const pid = r.meta?.panel_id ? String(r.meta.panel_id) : ''
                          return (
                              <span className="font-mono text-xs text-[var(--text-secondary)]">
                                  {r.episode_label ? `Ep.${r.episode_label}` : '-'}
                                  {pid ? ` · ${pid}` : ''}
                              </span>
                          )
                      },
                  },
              ]),
        {
            title: 'Token / 作图详情',
            key: 'detail',
            render: (_: unknown, r: UsageRecordItem) => {
                if (r.kind === 'image') {
                    const refs = Number(r.meta?.references || 0)
                    const preview = r.meta?.prompt_preview ? String(r.meta.prompt_preview) : ''
                    return (
                        <div className="space-y-0.5 text-xs">
                            <div className="font-mono text-[var(--text-primary)]">
                                {r.image_count} 张 · {r.image_size || '1024x1024'}
                                {refs > 0 ? ` · ${refs} 张参考图` : ''}
                            </div>
                            {preview && (
                                <div className="text-[11px] text-[var(--text-muted)] truncate max-w-md" title={preview}>
                                    {preview}
                                </div>
                            )}
                        </div>
                    )
                }
                const reasoning = Number(r.meta?.reasoning_tokens || 0)
                return (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-xs">
                        <Tooltip content={`输入 ${r.input_tokens.toLocaleString()} / 输出 ${r.output_tokens.toLocaleString()}`}>
                            <span className="text-[var(--text-primary)]">
                                入 {formatTokens(r.input_tokens)} · 出 {formatTokens(r.output_tokens)}
                            </span>
                        </Tooltip>
                        <Tooltip
                            content={`缓存读 ${r.cache_read_tokens.toLocaleString()} / 缓存写 ${r.cache_write_tokens.toLocaleString()}`}
                        >
                            <span className="text-[var(--text-secondary)]">
                                缓存读 {formatTokens(r.cache_read_tokens)} · 写 {formatTokens(r.cache_write_tokens)}
                            </span>
                        </Tooltip>
                        {r.cache_hit_rate > 0 && (
                            <span style={{ color: 'var(--status-ok)' }}>{r.cache_hit_rate.toFixed(1)}%</span>
                        )}
                        {reasoning > 0 && (
                            <span className="text-[var(--text-muted)]">思考 {formatTokens(reasoning)}</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: '耗时',
            dataIndex: 'duration_ms',
            key: 'duration_ms',
            width: 90,
            render: (ms: number) => (
                <span className="font-mono text-xs text-[var(--text-primary)]">{formatDuration(ms)}</span>
            ),
        },
        {
            title: '状态',
            dataIndex: 'status',
            key: 'status',
            width: 82,
            render: (st: string, r: UsageRecordItem) =>
                st === 'succeeded' ? (
                    <span className="font-mono text-[11px]" style={{ color: 'var(--status-ok)' }}>
                        OK
                    </span>
                ) : (
                    <Tooltip content={r.error || '调用失败'}>
                        <span className="font-mono text-[11px] text-[var(--accent)] cursor-help">FAIL</span>
                    </Tooltip>
                ),
        },
    ]

    return (
        <div className="space-y-6">
            {/* Top Controls Strip */}
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Select
                        size="small"
                        value={days ?? 0}
                        onChange={(v) => {
                            const n = Number(v)
                            setDays(n > 0 ? n : undefined)
                        }}
                        style={{ width: 120 }}
                    >
                        <Select.Option value={0}>全部时间</Select.Option>
                        <Select.Option value={7}>最近 7 天</Select.Option>
                        <Select.Option value={30}>最近 30 天</Select.Option>
                    </Select>
                    <span className="text-xs font-mono text-[var(--text-muted)]">
                        累计耗时 {formatDuration(totals?.total_duration_ms || 0)}
                    </span>
                </div>
                <Button
                    size="small"
                    icon={<IconRefresh />}
                    loading={summaryFetching || recordsFetching}
                    onClick={() => {
                        refetchSummary()
                        refetchRecords()
                    }}
                >
                    刷新统计
                </Button>
            </div>

            {/* Structured Hairline Summary Grid (No Colorful SaaS Cards) */}
            {summaryLoading ? (
                <div className="py-10 flex justify-center">
                    <Spin />
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-px bg-[var(--border)] rounded-[6px] overflow-hidden border border-[var(--border)]">
                    <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                        <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                            Total Tokens · 总消耗
                        </div>
                        <Tooltip content={`精确总计 ${(totals?.total_tokens || 0).toLocaleString()} tokens`}>
                            <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">
                                {formatTokens(totals?.total_tokens || 0)}
                            </div>
                        </Tooltip>
                        <div className="text-xs font-mono text-[var(--text-secondary)]">
                            输入 {formatTokens(totals?.input_tokens || 0)} · 输出 {formatTokens(totals?.output_tokens || 0)}
                        </div>
                    </div>

                    <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                        <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                            Prompt Cache · 缓存命中率
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span
                                className="text-2xl font-mono font-bold"
                                style={{
                                    color: (totals?.cache_hit_rate || 0) >= 30 ? 'var(--status-ok)' : 'var(--text-primary)',
                                }}
                            >
                                {(totals?.cache_hit_rate || 0).toFixed(1)}%
                            </span>
                            <span className="text-[11px] font-mono text-[var(--text-muted)]">cache read / input</span>
                        </div>
                        <div className="w-full h-1 rounded-full bg-[var(--bg-elevated)] overflow-hidden">
                            <div
                                className="h-full"
                                style={{
                                    width: `${Math.min(100, totals?.cache_hit_rate || 0)}%`,
                                    backgroundColor: 'var(--status-ok)',
                                }}
                            />
                        </div>
                        <div className="text-xs font-mono text-[var(--text-secondary)]">
                            缓存读 {formatTokens(totals?.cache_read_tokens || 0)} · 缓存写 {formatTokens(totals?.cache_write_tokens || 0)}
                        </div>
                    </div>

                    <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                        <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                            LLM Calls · 对话与理解
                        </div>
                        <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">
                            {totals?.llm_calls || 0}
                            <span className="text-xs font-normal text-[var(--text-muted)] ml-1.5">次</span>
                        </div>
                        <div className="text-xs font-mono text-[var(--text-secondary)]">
                            平均耗时 {formatDuration(totals?.avg_llm_duration_ms || 0)}
                            {(totals?.embedding_calls || 0) > 0 && ` · Embed ${totals?.embedding_calls}`}
                        </div>
                    </div>

                    <div className="bg-[var(--bg-panel)] p-4 space-y-1.5">
                        <div className="text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                            Image Gen · 作图记录
                        </div>
                        <div className="text-2xl font-mono font-bold text-[var(--text-primary)]">
                            {totals?.total_images || 0}
                            <span className="text-xs font-normal text-[var(--text-muted)] ml-1.5">张</span>
                        </div>
                        <div className="text-xs font-mono text-[var(--text-secondary)]">
                            调用 {totals?.image_calls || 0} 次 · 平均 {formatDuration(totals?.avg_image_duration_ms || 0)}
                            {(totals?.failed_calls || 0) > 0 && (
                                <span className="text-[var(--accent)] ml-1.5">({totals?.failed_calls} 失败)</span>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Daily Trend Strip (when data exists) */}
            {daily.length > 0 && (
                <section className="space-y-2">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                        每日 Token 与出图趋势 ({daily.length} 天)
                    </h3>
                    <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] p-4">
                        <div className="flex items-end gap-2 h-24 overflow-x-auto pb-1">
                            {daily.slice(-21).map((d) => {
                                const hPct = Math.max(6, Math.round((d.total_tokens / maxDailyTokens) * 100))
                                const cachePct =
                                    d.total_tokens > 0 ? Math.round((d.cache_read_tokens / d.total_tokens) * 100) : 0
                                return (
                                    <Tooltip
                                        key={d.date}
                                        content={`${d.date} | 总 Token ${formatTokens(d.total_tokens)} (缓存读 ${formatTokens(d.cache_read_tokens)}) | LLM ${d.llm_calls} 次 | 出图 ${d.image_count} 张`}
                                    >
                                        <div className="flex flex-col items-center gap-1 min-w-[28px] flex-1 max-w-[48px] h-full justify-end">
                                            <div
                                                className="w-full rounded-[2px] border relative overflow-hidden"
                                                style={{
                                                    height: `${hPct}%`,
                                                    backgroundColor: 'rgba(230, 75, 53, 0.28)',
                                                    borderColor: 'var(--accent)',
                                                }}
                                            >
                                                <div
                                                    className="absolute bottom-0 left-0 right-0"
                                                    style={{
                                                        height: `${Math.min(100, cachePct)}%`,
                                                        backgroundColor: 'var(--status-ok)',
                                                        opacity: 0.7,
                                                    }}
                                                />
                                            </div>
                                            <span className="text-[9px] font-mono text-[var(--text-muted)]">
                                                {d.date.slice(5)}
                                            </span>
                                        </div>
                                    </Tooltip>
                                )
                            })}
                        </div>
                    </div>
                </section>
            )}

            {/* Breakdown by Model */}
            <section className="space-y-2.5">
                <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                    按模型统计 ({byModel.length})
                </h3>
                <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                    {byModel.length === 0 ? (
                        <div className="py-8">
                            <Empty description="暂无模型调用记录。执行剧情理解、剧情侦探 QA、分镜生成或渲染作图后将自动记录。" />
                        </div>
                    ) : (
                        <Table
                            size="small"
                            rowKey={(r?: UsageByModelItem) => `${r?.kind}-${r?.provider}-${r?.model}`}
                            columns={modelColumns}
                            dataSource={byModel}
                            pagination={false}
                        />
                    )}
                </div>
            </section>

            {/* Detailed Call & Image Generation Logs */}
            <section className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                        调用与作图明细日志 ({recordsData?.total || 0})
                    </h3>
                    <div className="flex flex-wrap items-center gap-2">
                        <Select
                            size="small"
                            value={kindFilter || ''}
                            onChange={(v) => {
                                setKindFilter(v ? String(v) : undefined)
                                setPage(1)
                            }}
                            style={{ width: 120 }}
                        >
                            <Select.Option value="">全部类型</Select.Option>
                            <Select.Option value="llm">仅 LLM</Select.Option>
                            <Select.Option value="image">仅作图记录</Select.Option>
                            <Select.Option value="embedding">仅 Embedding</Select.Option>
                        </Select>
                        <Select
                            size="small"
                            value={modelFilter || ''}
                            onChange={(v) => {
                                setModelFilter(v ? String(v) : undefined)
                                setPage(1)
                            }}
                            style={{ width: 180 }}
                        >
                            <Select.Option value="">全部模型</Select.Option>
                            {modelOptions.map((m) => (
                                <Select.Option key={m} value={m}>
                                    {m}
                                </Select.Option>
                            ))}
                        </Select>
                    </div>
                </div>

                <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden">
                    <Table
                        size="small"
                        rowKey="id"
                        loading={recordsLoading}
                        columns={recordColumns}
                        dataSource={records}
                        empty={<Empty description="暂无调用明细记录" />}
                        pagination={{
                            currentPage: page,
                            pageSize,
                            total: recordsData?.total || 0,
                            showTotal: true,
                            onChange: (cp: number, ps: number) => {
                                setPage(cp)
                                setPageSize(ps)
                            },
                        }}
                    />
                </div>
            </section>
        </div>
    )
}
