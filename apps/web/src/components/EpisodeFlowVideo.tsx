import { browserStatus } from './FlowBrowserPair'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Popconfirm, Select, Spin, TextArea } from '@douyinfe/semi-ui'
import { flowService } from '@/services/flow'
import type { FlowOptions, FlowRun } from '@/services/flow'
import { storageFileUrl } from '@/services/project'

const active = (r: FlowRun) => r.status === 'queued' || r.status === 'running'
const statusText = { queued: '排队中', running: '进行中', succeeded: '已完成', failed: '失败' }

export default function EpisodeFlowVideo({ episodeId }: { episodeId: string }) {
    const cache = useQueryClient()
    const [provider, setProvider] = useState('')
    const [options, setOptions] = useState<FlowOptions>({ model: 'veo-3.1-lite', aspect_ratio: 'landscape', pages_per_clip: 2 })
    const [edits, setEdits] = useState<{ plan: string; prompts: Record<number, string> }>({ plan: '', prompts: {} })
    const connections = useQuery({ queryKey: ['flow-accounts'], queryFn: flowService.accounts, refetchInterval: 7000 })
    const accounts = connections.data || []
    const account = accounts.find(a => a.id === provider || (!provider && accounts.length === 1))
    let settingsPath = '/models#flow-accounts'
    if (account) settingsPath = `/models?flow=${encodeURIComponent(account.id)}`
    else if (connections.isSuccess && !accounts.length) settingsPath = '/models?flow=new'
    const preview = useQuery({
        queryKey: ['flow-plan', episodeId, options], queryFn: () => flowService.plan(episodeId, options), retry: false,
    })
    const historyKey = ['flow-runs', episodeId]
    const history = useQuery({
        queryKey: historyKey, queryFn: () => flowService.runs(episodeId),
        refetchInterval: q => q.state.data?.some(active) ? 3500 : false,
    })
    const plan = preview.data
    const prompts = plan?.shots.map((s, i) => (edits.plan === plan.plan_id ? edits.prompts[i] : undefined) ?? s.prompt) || []
    const refresh = (run: FlowRun) => {
        cache.setQueryData<FlowRun[]>(historyKey, prev => [run, ...(prev || []).filter(r => r.id !== run.id)])
        cache.invalidateQueries({ queryKey: historyKey })
        cache.invalidateQueries({ queryKey: ['generation-runs', episodeId] })
    }
    const start = useMutation({
        mutationFn: (mode: FlowRun['mode']) => flowService.start(episodeId, {
            ...options, mode, provider_id: account!.id, connection_id: account!.connection_id!, plan_id: plan!.plan_id,
            prompts: mode === 'video' ? prompts : undefined, request_id: globalThis.crypto?.randomUUID?.(),
        }),
        onSuccess: refresh,
        onError: () => { preview.refetch(); history.refetch(); connections.refetch() },
    })
    const resume = useMutation({
        mutationFn: (r: FlowRun) => flowService.resume(episodeId, r.id, account!.id, r.uncertain),
        onSuccess: refresh,
        onError: () => { history.refetch(); connections.refetch() },
    })
    const busy = start.isPending || resume.isPending || !!history.data?.some(active)
    const ready = account?.status === 'ready' && !!account.connection_id
    const disabled = busy || !ready || !plan?.shots.length || !history.isSuccess
    const refs = new Map(plan?.sources.map(s => [s.key, s]))

    const failureDetails = (run: FlowRun) => {
        if (run.status !== 'failed') return null
        const reason = run.error && <p className="text-[var(--status-error)]">{run.error}</p>
        if (run.legacy || !connections.isSuccess) return reason
        const original = accounts.find(a => a.id === run.provider_id && a.connection_id === run.connection_id)
        if (!original) {
            const restartSync = run.mode === 'sync' && run.id === history.data?.[0]?.id
            return <>
                <p>原 Flow 连接已移除或更换。{run.mode === 'video' && '请先查看原 Flow 项目的生成记录，再决定是否新建视频任务。'}</p>
                {restartSync && <Button size="small" disabled={disabled} onClick={() => start.mutate('sync')}>
                    用当前连接重新同步素材
                </Button>}
            </>
        }
        if (account?.id !== original.id) return <>{reason}<p>选择「{original.name}」可继续此任务。</p></>
        if (!ready) return <>{reason}<p>打开本次任务使用的 Flow 标签页，待扩展上线后可继续。</p></>
        return <>{reason}{run.uncertain ? (
            <Popconfirm title="上次提交结果未知" content="请先在 Flow 核对。再次提交这个镜头可能消耗额外积分。"
                onConfirm={() => resume.mutate(run)}>
                <Button size="small" disabled={busy}>重新提交未确认的镜头</Button>
            </Popconfirm>
        ) : <Button size="small" disabled={busy} onClick={() => resume.mutate(run)}>从中断处继续</Button>}</>
    }

    return (
        <section className="space-y-5 pt-3">
            <div className="flex flex-wrap items-end gap-4">
                <label className="grid gap-1 text-sm">Flow 连接
                    <Select aria-label="Flow 连接" value={account?.id} onChange={v => setProvider(String(v))}
                        placeholder={accounts.length ? '选择本次使用的连接' : '尚无可用 Flow 连接'} style={{ minWidth: 196 }}
                        optionList={accounts.map(a => ({ value: a.id, label: a.name + ' · ' + browserStatus(a.status) }))} />
                </label>
                <label className="grid gap-1 text-sm">视频模型
                    <Select aria-label="视频模型" value={options.model} onChange={v => setOptions({ ...options, model: v as FlowOptions['model'] })}
                        optionList={[{ value: 'veo-3.1-lite', label: 'Veo 3.1 Lite' }, { value: 'omni-flash-1.2', label: 'Omni 1.2 Flash' }]} />
                </label>
                <label className="grid gap-1 text-sm">画幅
                    <Select aria-label="画幅" value={options.aspect_ratio} onChange={v => setOptions({ ...options, aspect_ratio: v as FlowOptions['aspect_ratio'] })}
                        optionList={[{ value: 'landscape', label: '横屏 16:9' }, { value: 'portrait', label: '竖屏 9:16' }]} />
                </label>
                <label className="grid gap-1 text-sm">镜头节奏
                    <Select aria-label="镜头节奏" value={options.pages_per_clip} onChange={v => setOptions({ ...options, pages_per_clip: Number(v) as 1 | 2 })}
                        optionList={[{ value: 1, label: '每张画面一个镜头' }, { value: 2, label: '每两张画面一个镜头' }]} />
                </label>
                <Link to={settingsPath} className="text-sm text-[var(--accent)]">配置 Flow 扩展</Link>
            </div>
            {!!history.data?.length && <h3 className="text-base mb-0">本话视频任务</h3>}
            {history.data?.map(r => (
                <article key={r.id} className="rounded border border-[var(--border)] p-3 space-y-2 text-sm">
                    <div className="flex flex-wrap justify-between gap-2">
                        <strong>{r.mode === 'sync' ? '同步素材' : r.model} · {r.waiting_for === 'upload_rights' ? '等待确认素材使用权' : statusText[r.status]}</strong>
                        <span>{new Date(r.created_at).toLocaleString()}</span>
                    </div>
                    <div>已同步 {r.synced}/{r.sources} 张{r.mode === 'video' && ` · 已完成 ${r.completed}/${r.clips} 个镜头`}
                        {r.remote_id && !r.legacy && <> · <a className="text-[var(--accent)]" target="_blank" rel="noreferrer"
                            href={r.project_url || `https://flow.google.com/project/${encodeURIComponent(r.remote_id)}`}>{r.project_title || '打开 Flow 项目'} ↗</a></>}
                    </div>
                    {r.waiting_for === 'upload_rights' && <p role="status">请回到扩展正在使用的 Flow 标签页。确认有权上传后点「I agree」，本话会从当前素材继续同步。</p>}
                    {failureDetails(r)}
                    {r.output_key && <>
                        <video className="block w-full max-w-2xl rounded" controls preload="metadata" src={storageFileUrl(r.output_key)} />
                        <a className="text-[var(--accent)]" href={storageFileUrl(r.output_key)} download>下载本话 MP4</a>
                    </>}
                </article>
            ))}
            {preview.isPending ? <Spin /> : preview.isError ? (
                <Button onClick={() => preview.refetch()}>重新读取镜头方案</Button>
            ) : !plan?.shots.length ? (
                <Empty description="导入漫画页、生成分镜原画或完成排版后，就能预览本话的视频镜头。" />
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-3 border-y border-[var(--border)] py-3">
                        <div>
                            <strong>{plan.shots.length} 个镜头 · 约 {plan.shots.length * 8} 秒</strong>
                            <p className="text-xs text-[var(--text-muted)] mt-1 mb-0">
                                将同步本话 {plan.sources.length} 张素材。生成会向所选账号提交 {plan.shots.length} 个视频任务，积分由浏览器中登录的 Google Flow 账号结算。
                            </p>
                        </div>
                        <div className="flex gap-2">
                            <Button disabled={disabled} onClick={() => start.mutate('sync')}>仅同步素材</Button>
                            <Button theme="solid" disabled={disabled || prompts.some(p => !p.trim())}
                                loading={start.isPending} onClick={() => start.mutate('video')}>生成本话视频</Button>
                        </div>
                    </div>
                    <div className="space-y-2">
                        {plan.shots.map((shot, i) => (
                            <details key={plan.plan_id + i} className="rounded border border-[var(--border)] px-3 py-2">
                                <summary className="cursor-pointer text-sm">镜头 {i + 1} · {shot.label}</summary>
                                <div className="flex gap-2 flex-wrap my-3">
                                    {shot.references.map(key => (
                                        <figure key={key} className="m-0">
                                            <img src={storageFileUrl(key)} alt={refs.get(key)?.label} loading="lazy"
                                                className="h-20 w-16 object-contain rounded bg-[var(--bg-elevated)]" />
                                            <figcaption className="text-xs text-[var(--text-muted)]">{refs.get(key)?.label}</figcaption>
                                        </figure>
                                    ))}
                                </div>
                                <TextArea aria-label={`镜头 ${i + 1} 提示词`} value={prompts[i]} maxLength={4000} rows={5}
                                    onChange={v => setEdits(prev => ({ plan: plan.plan_id,
                                        prompts: { ...(prev.plan === plan.plan_id ? prev.prompts : {}), [i]: v } }))} />
                            </details>
                        ))}
                    </div>
                </>
            )}
        </section>
    )
}
