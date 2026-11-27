import FlowBrowserPair, { browserStatus } from '@/components/FlowBrowserPair'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Checkbox, Empty, Input, Modal, Popconfirm, Select, Spin, Tag, Toast } from '@douyinfe/semi-ui'
import { IconDelete, IconEdit, IconPlus, IconRefresh } from '@douyinfe/semi-icons'
import { providerService } from '@/services/project'
import type { ModelProviderItem, ProviderPreset, RoleBindingItem } from '@/services/project'

const ROLE_META: Record<string, { title: string; subtitle: string; code: string }> = {
    main_llm: {
        code: '01',
        title: '主推理与分镜编剧',
        subtitle: '负责分镜剧本生成、连续性审校、剧情侦探 QA 与 Render Agent 调度',
    },
    vision_llm: {
        code: '02',
        title: '多模态漫画识图理解',
        subtitle: '负责读取漫画原稿、逐页 OCR 与人物/伏笔提取（留空自动复用主模型）',
    },
    image_gen: {
        code: '03',
        title: '原画渲染与作图引擎',
        subtitle: '用于绘制漫画分镜原画。漫画转视频直接使用章节中已有的画面。',
    },
    embedding: {
        code: '04',
        title: '向量检索嵌入（可选）',
        subtitle: '用于跨章节语义向量召回；留空时自动优雅降级为内置多路 CJK 分词检索',
    },
}

const CATEGORY_SECTIONS: Array<{ key: string; label: string }> = [
    { key: 'aggregator', label: '全网聚合路由' },
    { key: 'global', label: '国际主流模型' },
    { key: 'china', label: '国内主流模型 & Coding Plan' },
    { key: 'image', label: '图像与视频工作流' },
    { key: 'custom', label: '自定义 OpenAI 兼容网关' },
]

function formatCtx(ctx?: number | null): string {
    if (!ctx) return ''
    if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(ctx % 1_000_000 === 0 ? 0 : 1)}M`
    return `${Math.round(ctx / 1000)}K`
}

export default function ModelsPage() {
    const queryClient = useQueryClient()
    const [searchParams, setSearchParams] = useSearchParams()
    const { data, isLoading, refetch, isFetching } = useQuery({
        queryKey: ['providers-overview'],
        queryFn: () => providerService.overview(),
        refetchInterval: q => q.state.data?.providers.some(p => p.preset_key === 'google_flow_browser') ? 10000 : false,
    })

    // Modal state for Create / Edit provider
    const [modalOpen, setModalOpen] = useState(false)
    const [editingProvider, setEditingProvider] = useState<ModelProviderItem | null>(null)
    const [activePreset, setActivePreset] = useState<ProviderPreset | null>(null)

    const [formName, setFormName] = useState('')
    const [formBaseUrl, setFormBaseUrl] = useState('')
    const [formApiKey, setFormApiKey] = useState('')
    const isFlow = activePreset?.key === 'google_flow_browser'
    const [formDefaultModel, setFormDefaultModel] = useState('')
    const [formModels, setFormModels] = useState<string[]>([])
    const [activateRoles, setActivateRoles] = useState<string[]>(['main_llm'])
    const [testing, setTesting] = useState(false)
    const [testResult, setTestResult] = useState<{ ok: boolean; latency_ms: number; message: string } | null>(null)

    // Per-role draft selections
    const [roleDrafts, setRoleDrafts] = useState<
        Record<string, { provider_id: string; model_id: string; concurrency: number }>
    >({})

    const presets = data?.presets || []
    const providers = data?.providers || []
    const roles = data?.roles || []
    const presetByKey = new Map(presets.map((p) => [p.key, p]))
    const providerById = new Map(providers.map((p) => [p.id, p]))
    const flowPreset = presetByKey.get('google_flow_browser')
    const flowAccounts = providers.filter(p => p.preset_key === 'google_flow_browser' && p.enabled)

    const openPresetModal = useCallback((preset: ProviderPreset) => {
        setEditingProvider(null)
        setActivePreset(preset)
        setFormName(preset.name)
        setFormBaseUrl(preset.base_url)
        setFormApiKey('')
        setFormDefaultModel(preset.default_model)
        setFormModels(preset.models.map((m) => m.id))
        const defaultRoles: string[] = []
        if (preset.supports_llm) defaultRoles.push('main_llm')
        else if (preset.supports_image && preset.key !== 'google_flow_browser') defaultRoles.push('image_gen')
        setActivateRoles(defaultRoles)
        setTestResult(null)
        setModalOpen(true)
    }, [])

    const openEditModal = useCallback((p: ModelProviderItem) => {
        const preset = data?.presets.find(item => item.key === p.preset_key) || null
        setEditingProvider(p)
        setActivePreset(preset)
        setFormName(p.name)
        setFormBaseUrl(p.base_url)
        setFormApiKey('')
        setFormDefaultModel(p.default_model)
        setFormModels(p.models_cache || [])
        setActivateRoles([])
        setTestResult(
            p.last_test_status
                ? {
                      ok: p.last_test_status === 'ok',
                      latency_ms: 0,
                      message: p.last_test_message || '',
                  }
                : null,
        )
        setModalOpen(true)
    }, [data?.presets])

    useEffect(() => {
        const target = searchParams.get('flow')
        if (!target || !data) return
        const existing = data.providers.find(p => p.preset_key === 'google_flow_browser' && p.id === target)
        if (existing) openEditModal(existing)
        else if (target === 'new' && flowPreset) openPresetModal(flowPreset)
        const next = new URLSearchParams(searchParams)
        next.delete('flow')
        setSearchParams(next, { replace: true })
    }, [data, flowPreset, searchParams, setSearchParams, openEditModal, openPresetModal])

    const saveMutation = useMutation({
        mutationFn: async () => {
            if (!formName.trim()) throw new Error('请填写服务商显示名称')
            if (isFlow) {
                const name = formName.trim()
                return editingProvider
                    ? providerService.update(editingProvider.id, { name })
                    : providerService.create({ name, preset_key: 'google_flow_browser' })
            }
            if (editingProvider) {
                return providerService.update(editingProvider.id, {
                    name: formName.trim(),
                    base_url: formBaseUrl.trim(),
                    api_key: formApiKey.trim() || undefined,
                    default_model: formDefaultModel.trim(),
                    models_cache: formModels,
                })
            }
            return providerService.create({
                preset_key: activePreset?.key || 'custom',
                name: formName.trim(),
                interface_type: activePreset?.interface_type || 'openai_compatible',
                base_url: formBaseUrl.trim(),
                api_key: formApiKey.trim() || undefined,
                default_model: formDefaultModel.trim(),
                models_cache: formModels,
                extra_headers: activePreset?.extra_headers,
                activate_roles: activateRoles,
            })
        },
        onSuccess: saved => {
            Toast.success(editingProvider ? '服务商配置已更新（实时生效）' : '服务商已接入并实时生效')
            if (isFlow && !editingProvider) openEditModal(saved)
            else setModalOpen(false)
            queryClient.invalidateQueries({ queryKey: ['providers-overview'] })
            if (isFlow) queryClient.invalidateQueries({ queryKey: ['flow-accounts'] })
        },
        onError: (err: unknown) => {
            Toast.error(err instanceof Error ? err.message : '保存失败')
        },
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => providerService.remove(id),
        onSuccess: () => {
            Toast.success('服务商已移除')
            queryClient.invalidateQueries({ queryKey: ['providers-overview'] })
            queryClient.invalidateQueries({ queryKey: ['flow-accounts'] })
        },
    })

    const roleMutation = useMutation({
        mutationFn: (payload: {
            role: string
            provider_id: string | null
            model_id: string | null
            params?: Record<string, unknown>
        }) =>
            providerService.updateRole(payload.role, {
                provider_id: payload.provider_id,
                model_id: payload.model_id,
                params: payload.params,
            }),
        onSuccess: (updated) => {
            Toast.success(`${ROLE_META[updated.role]?.title || updated.role} 已实时切换至 ${updated.effective_model || updated.effective_provider}`)
            queryClient.invalidateQueries({ queryKey: ['providers-overview'] })
        },
    })

    const handleTestInModal = async () => {
        setTesting(true)
        setTestResult(null)
        try {
            const res = await providerService.test({
                provider_id: editingProvider?.id,
                preset_key: editingProvider?.preset_key || activePreset?.key || 'custom',
                interface_type: editingProvider?.interface_type || activePreset?.interface_type || 'openai_compatible',
                base_url: formBaseUrl.trim(),
                api_key: isFlow ? undefined : formApiKey.trim() || undefined,
                model: formDefaultModel.trim() || undefined,
                extra_headers: activePreset?.extra_headers,
            })
            setTestResult(res)
            if (res.models.length > 0) {
                setFormModels((prev) => Array.from(new Set([...res.models, ...prev])))
                if (!formDefaultModel.trim()) {
                    setFormDefaultModel(res.models[0])
                }
            }
            if (res.ok) Toast.success(res.message)
            else Toast.error(res.message)
        } catch {
            Toast.error('连接探测请求失败')
        } finally {
            setTesting(false)
        }
    }

    const handleQuickTestProvider = async (p: ModelProviderItem) => {
        try {
            const res = await providerService.test({ provider_id: p.id })
            if (res.ok) Toast.success(`${p.name}: ${res.message} (${res.latency_ms}ms)`)
            else Toast.error(`${p.name}: ${res.message}`)
            queryClient.invalidateQueries({ queryKey: ['providers-overview'] })
        } catch {
            Toast.error('测试连接失败')
        }
    }

    const getRoleDraft = (item: RoleBindingItem) => {
        if (roleDrafts[item.role]) return roleDrafts[item.role]
        const rawConc = Number((item.params || {}).concurrency || 1)
        const safeConc = Number.isFinite(rawConc) ? Math.max(1, Math.min(8, Math.round(rawConc))) : 1
        return {
            provider_id: item.provider_id || '',
            model_id: item.model_id || '',
            concurrency: safeConc,
        }
    }

    const setRoleDraft = (
        role: string,
        next: { provider_id: string; model_id: string; concurrency: number },
    ) => {
        setRoleDrafts((prev) => ({ ...prev, [role]: next }))
    }

    if (isLoading) {
        return (
            <div className="py-20 flex justify-center">
                <Spin size="large" />
            </div>
        )
    }

    return (
        <div className="space-y-8">
            {/* Editorial Header */}
            <header className="pb-4 border-b border-[var(--border)] flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div className="space-y-1.5">
                    <h1 className="font-editorial text-2xl font-bold tracking-tight text-[var(--text-primary)] m-0">
                        模型与服务商管理
                    </h1>
                    <p className="text-sm text-[var(--text-secondary)] m-0">
                        在此配置服务商与 Flow 扩展，再按角色分配推理、识图、作图与向量模型。
                    </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <Button icon={<IconRefresh />} loading={isFetching} onClick={() => refetch()}>
                        刷新状态
                    </Button>
                    <Button
                        theme="solid"
                        icon={<IconPlus />}
                        onClick={() => {
                            const custom = presetByKey.get('custom') || presets[0]
                            if (custom) openPresetModal(custom)
                        }}
                    >
                        添加自定义服务商
                    </Button>
                </div>
            </header>

            {flowPreset && <section id="flow-accounts" className="flex flex-wrap items-center justify-between gap-3 rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] p-4">
                <div>
                    <h2 className="m-0 text-sm font-semibold">漫画转视频 · Google Flow</h2>
                    <p className="mt-1 mb-0 text-xs text-[var(--text-muted)]">在 Flow 网页中选择 Google 账号，在章节里选择连接和视频模型。</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {flowAccounts.map(p => <Button key={p.id} size="small" onClick={() => openEditModal(p)}>
                        {p.name} · {browserStatus(p.flow_status)}
                    </Button>)}
                    <Button size="small" icon={<IconPlus />} onClick={() => openPresetModal(flowPreset)}>添加 Flow 连接</Button>
                </div>
            </section>}

            {/* SECTION 1: 4-ROLE MODEL ROUTING */}
            <section className="space-y-3">
                <div className="flex items-center justify-between">
                    <h2 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                        Active Role Routing · 按任务角色路由模型
                    </h2>
                    <span className="text-xs text-[var(--text-muted)]">
                        支持混搭：例如 DeepSeek 写分镜 + GLM/Gemini 漫画识图 + Nano Banana / GPT-Image 作图
                    </span>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-[var(--border)] rounded-[6px] overflow-hidden border border-[var(--border)]">
                    {roles.map((r) => {
                        const meta = ROLE_META[r.role] || { code: '00', title: r.role, subtitle: '' }
                        const draft = getRoleDraft(r)
                        const chosenProvider = draft.provider_id ? providerById.get(draft.provider_id) : null
                        const chosenPreset = chosenProvider ? presetByKey.get(chosenProvider.preset_key) : null
                        const candidateModels = Array.from(
                            new Set([
                                ...(chosenProvider?.models_cache || []),
                                ...(chosenPreset?.models.map((m) => m.id) || []),
                                ...(chosenProvider?.default_model ? [chosenProvider.default_model] : []),
                            ]),
                        ).filter(Boolean)

                        return (
                            <div key={r.role} className="bg-[var(--bg-panel)] p-4 space-y-3">
                                <div className="flex items-start justify-between gap-2">
                                    <div className="space-y-0.5">
                                        <div className="flex items-center gap-2">
                                            <span className="font-mono text-xs font-semibold text-[var(--accent)]">
                                                {meta.code}
                                            </span>
                                            <span className="text-sm font-semibold text-[var(--text-primary)]">
                                                {meta.title}
                                            </span>
                                        </div>
                                        <p className="text-xs text-[var(--text-muted)] m-0">{meta.subtitle}</p>
                                    </div>
                                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[4px] border border-[var(--border)] bg-[var(--bg-elevated)] font-mono text-[11px] shrink-0">
                                        <span
                                            className="w-1.5 h-1.5 rounded-full"
                                            style={{
                                                backgroundColor:
                                                    r.effective_source === 'database'
                                                        ? 'var(--status-ok)'
                                                        : 'var(--text-muted)',
                                            }}
                                        />
                                        <span className="text-[var(--text-secondary)]">
                                            {r.effective_source === 'database' ? 'Web 生效' : '.env 回退'}
                                        </span>
                                    </span>
                                </div>

                                <div className="rounded-[4px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] px-3 py-2 text-xs font-mono text-[var(--text-secondary)] flex items-center justify-between gap-2">
                                    <span className="truncate">
                                        当前生效：<strong className="text-[var(--text-primary)]">{r.effective_provider}</strong>
                                        {' / '}
                                        <strong className="text-[var(--text-primary)]">{r.effective_model || '未启用'}</strong>
                                    </span>
                                </div>

                                <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
                                    <div className="sm:col-span-5">
                                        <Select
                                            size="small"
                                            style={{ width: '100%' }}
                                            value={draft.provider_id}
                                            placeholder="自动回退 (.env / 继承主模型)"
                                            onChange={(v) => {
                                                const pid = String(v || '')
                                                const prov = providerById.get(pid)
                                                setRoleDraft(r.role, {
                                                    ...draft,
                                                    provider_id: pid,
                                                    model_id: prov?.default_model || '',
                                                })
                                            }}
                                        >
                                            <Select.Option value="">
                                                {r.role === 'vision_llm' ? '自动继承主模型' : '使用 .env 默认配置'}
                                            </Select.Option>
                                            {providers.filter(p => p.preset_key !== 'google_flow' && (p.preset_key !== 'google_flow_browser' || r.role === 'image_gen')).map((p) => (
                                                <Select.Option key={p.id} value={p.id}>
                                                    {p.name}
                                                </Select.Option>
                                            ))}
                                        </Select>
                                    </div>
                                    <div className="sm:col-span-5">
                                        <Input
                                            size="small"
                                            disabled={!draft.provider_id}
                                            value={draft.model_id}
                                            placeholder={chosenProvider?.default_model || '输入模型 ID'}
                                            onChange={(val) =>
                                                setRoleDraft(r.role, { ...draft, model_id: val })
                                            }
                                        />
                                    </div>
                                    <div className="sm:col-span-2 flex justify-end">
                                        <Button
                                            size="small"
                                            theme="solid"
                                            loading={roleMutation.isPending}
                                            onClick={() =>
                                                roleMutation.mutate({
                                                    role: r.role,
                                                    provider_id: draft.provider_id || null,
                                                    model_id: draft.model_id.trim() || null,
                                                    params:
                                                        r.role === 'vision_llm'
                                                            ? { ...(r.params || {}), concurrency: draft.concurrency }
                                                            : r.params,
                                                })
                                            }
                                        >
                                            应用
                                        </Button>
                                    </div>
                                </div>

                                {r.role === 'vision_llm' && (
                                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-3 py-2">
                                        <div className="space-y-0.5">
                                            <div className="text-xs font-medium text-[var(--text-primary)]">
                                                单话视觉理解并发数 (Concurrency)
                                            </div>
                                            <div className="text-[11px] text-[var(--text-muted)]">
                                                话间始终严格串行；若使用高并发 API 服务商（如 Gemini / OpenRouter / OpenAI），调大并发可成倍提速
                                            </div>
                                        </div>
                                        <Select
                                            size="small"
                                            style={{ width: 204 }}
                                            value={draft.concurrency}
                                            onChange={(v) =>
                                                setRoleDraft(r.role, { ...draft, concurrency: Number(v) || 1 })
                                            }
                                        >
                                            <Select.Option value={1}>1x · 严格串行 (零盲区)</Select.Option>
                                            <Select.Option value={2}>2x · 轻度并发</Select.Option>
                                            <Select.Option value={3}>3x · 中等并发</Select.Option>
                                            <Select.Option value={4}>4x · 高速并发</Select.Option>
                                            <Select.Option value={6}>6x · 极速并发</Select.Option>
                                            <Select.Option value={8}>8x · 最大并发</Select.Option>
                                        </Select>
                                    </div>
                                )}

                                {draft.provider_id && candidateModels.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                        {candidateModels.slice(0, 8).map((mid) => {
                                            const active = draft.model_id === mid
                                            return (
                                                <button
                                                    key={mid}
                                                    type="button"
                                                    onClick={() =>
                                                        setRoleDraft(r.role, { ...draft, model_id: mid })
                                                    }
                                                    className="px-2 py-0.5 rounded-[4px] border text-[11px] font-mono cursor-pointer transition-colors"
                                                    style={{
                                                        backgroundColor: active
                                                            ? 'var(--accent-soft)'
                                                            : 'var(--bg-elevated)',
                                                        borderColor: active ? 'var(--accent)' : 'var(--border)',
                                                        color: active ? 'var(--accent)' : 'var(--text-secondary)',
                                                    }}
                                                >
                                                    {mid}
                                                </button>
                                            )
                                        })}
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            </section>

            {/* SECTION 2: CONFIGURED PROVIDERS */}
            <section className="space-y-3">
                <h2 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                    Configured Providers · 已接入的服务商 ({providers.length})
                </h2>
                {providers.length === 0 ? (
                    <div className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] py-8">
                        <Empty description="目前使用环境配置。选择下方服务商或本地连接器即可接入。" />
                    </div>
                ) : (
                    <div className="divide-y divide-[var(--border)] rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)]">
                        {providers.map((p) => {
                            const boundRoles = roles.filter((r) => r.provider_id === p.id).map((r) => ROLE_META[r.role]?.title || r.role)
                            return (
                                <div
                                    key={p.id}
                                    className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-3"
                                >
                                    <div className="space-y-1 min-w-0">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-sm font-semibold text-[var(--text-primary)]">
                                                {p.name}
                                            </span>
                                            <span className="px-1.5 py-0.5 rounded-[4px] border border-[var(--border)] bg-[var(--bg-elevated)] font-mono text-[11px] text-[var(--text-muted)]">
                                                {p.preset_key}
                                            </span>
                                            {p.preset_key === 'google_flow_browser' && <Tag size="small">漫画转视频</Tag>}
                                            {p.default_model && p.preset_key !== 'google_flow_browser' && (
                                                <span className="font-mono text-xs text-[var(--text-secondary)]">
                                                    默认：{p.default_model}
                                                </span>
                                            )}
                                            {boundRoles.map((rl) => (
                                                <Tag key={rl} size="small" color="green">
                                                    {rl}
                                                </Tag>
                                            ))}
                                        </div>
                                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-mono text-[var(--text-muted)]">
                                            <span className="truncate max-w-md">
                                                {(p.base_url || '(默认端点)').replace(/^\/(?:home|Users)\/[^/]+\//, '~/')}
                                            </span>
                                            {p.preset_key === 'google_flow_browser' ? <span>{browserStatus(p.flow_status)}</span>
                                                : p.preset_key === 'google_flow' ? <span>旧中转已停用</span>
                                                : <span>Key: {p.has_api_key ? p.api_key_masked : '无鉴权'}</span>}
                                            {p.last_test_status && (
                                                <span
                                                    style={{
                                                        color:
                                                            p.last_test_status === 'ok'
                                                                ? 'var(--status-ok)'
                                                                : 'var(--accent)',
                                                    }}
                                                >
                                                    {p.last_test_status === 'ok' ? '● 连接正常' : `● ${p.last_test_message}`}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                                        <Button size="small" onClick={() => handleQuickTestProvider(p)}>
                                            测试连接
                                        </Button>
                                        <Button disabled={p.preset_key === 'google_flow'} size="small" icon={<IconEdit />} onClick={() => openEditModal(p)}>
                                            {p.preset_key === 'google_flow_browser' ? '配置连接' : '编辑'}
                                        </Button>
                                        <Popconfirm
                                            title={`确认移除服务商「${p.name}」？`}
                                            content="移除后绑定了该服务商的角色将自动回退到 .env 配置。"
                                            onConfirm={() => deleteMutation.mutate(p.id)}
                                        >
                                            <Button size="small" type="danger" theme="borderless" icon={<IconDelete />} />
                                        </Popconfirm>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </section>

            {/* SECTION 3: ONE-CLICK PRESET CATALOG */}
            <section className="space-y-5">
                <h2 className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)] m-0">
                    Quick-Connect Presets · 主流模型与本地连接器
                </h2>

                {CATEGORY_SECTIONS.map((cat) => {
                    const items = presets.filter((p) => p.category === cat.key)
                    if (items.length === 0) return null
                    return (
                        <div key={cat.key} className="space-y-2.5">
                            <div className="text-xs font-medium text-[var(--text-secondary)]">{cat.label}</div>
                            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                                {items.map((preset) => {
                                    const alreadyCount = providers.filter((p) => p.preset_key === preset.key).length
                                    return (
                                        <div
                                            key={preset.key}
                                            onClick={() => openPresetModal(preset)}
                                            className="rounded-[6px] border border-[var(--border)] bg-[var(--bg-panel)] hover:border-[var(--accent)] p-4 cursor-pointer transition-colors flex flex-col justify-between gap-3"
                                        >
                                            <div className="space-y-1.5">
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                                                        {preset.name}
                                                    </span>
                                                    {alreadyCount > 0 ? (
                                                        <span className="font-mono text-[11px] px-1.5 py-0.5 rounded-[4px] bg-[var(--bg-elevated)] text-[var(--status-ok)]">
                                                            已接入 {alreadyCount}
                                                        </span>
                                                    ) : (
                                                        <span className="font-mono text-[11px] text-[var(--accent)]">
                                                            + 接入
                                                        </span>
                                                    )}
                                                </div>
                                                <p className="text-[13px] text-[var(--text-secondary)] m-0 leading-relaxed">
                                                    {preset.description}
                                                </p>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[var(--border-subtle)] text-[11px] font-mono text-[var(--text-muted)]">
                                                {preset.supports_llm && (
                                                    <span className="px-1.5 py-0.5 rounded-[3px] bg-[var(--bg-elevated)]">
                                                        LLM
                                                    </span>
                                                )}
                                                {preset.supports_vision && (
                                                    <span className="px-1.5 py-0.5 rounded-[3px] bg-[var(--bg-elevated)]">
                                                        识图
                                                    </span>
                                                )}
                                                {preset.supports_image && (
                                                    <span className="px-1.5 py-0.5 rounded-[3px] bg-[var(--bg-elevated)]">
                                                        作图
                                                    </span>
                                                )}
                                                {preset.supports_embedding && (
                                                    <span className="px-1.5 py-0.5 rounded-[3px] bg-[var(--bg-elevated)]">
                                                        Embedding
                                                    </span>
                                                )}
                                                {preset.default_model && (
                                                    <span className="ml-auto truncate max-w-[160px]">
                                                        {preset.default_model}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    )
                })}
            </section>

            {/* CREATE / EDIT PROVIDER MODAL */}
            <Modal
                title={isFlow ? 'Google Flow 视频连接' : editingProvider ? `编辑服务商 · ${editingProvider.name}` : `接入服务商 · ${activePreset?.name || '自定义'}`}
                visible={modalOpen}
                onCancel={() => setModalOpen(false)}
                width={620}
                footer={
                    <div className="flex items-center justify-between gap-2">
                        <Button loading={testing} onClick={handleTestInModal}>
                            {isFlow ? '测试 Flow 连接' : '测试连接 & 拉取模型'}
                        </Button>
                        <div className="flex gap-2">
                            <Button onClick={() => setModalOpen(false)}>取消</Button>
                            <Button theme="solid" loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
                                {editingProvider ? '保存修改' : '保存并启用'}
                            </Button>
                        </div>
                    </div>
                }
            >
                <div className="space-y-4 text-xs">
                    {activePreset?.description && (
                        <div className="rounded-[4px] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[var(--text-secondary)] flex items-center justify-between gap-2">
                            <span>{activePreset.description}</span>
                            {activePreset.docs_url && !isFlow && (
                                <a
                                    href={activePreset.docs_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-[var(--accent)] hover:underline shrink-0"
                                >
                                    获取 Key →
                                </a>
                            )}
                        </div>
                    )}

                    <div className={isFlow ? '' : 'grid grid-cols-1 md:grid-cols-2 gap-3'}>
                        <div>
                            <label className="block text-[13px] font-medium text-[var(--text-primary)] mb-1">
                                显示名称
                            </label>
                            <Input value={formName} onChange={setFormName} placeholder="例如：智谱 Coding Plan" />
                        </div>
                        {!isFlow && <div>
                            <label className="block text-[13px] font-medium text-[var(--text-primary)] mb-1">
                                默认模型 ID（可手填任意最新模型）
                            </label>
                            <Input
                                value={formDefaultModel}
                                onChange={setFormDefaultModel}
                                placeholder={activePreset?.default_model || '例如：glm-5.4 / gpt-4.1 / claude-sonnet-4-5'}
                            />
                        </div>}
                    </div>

                    <div>
                        <label className="block text-[13px] font-medium text-[var(--text-primary)] mb-1">
                            {(editingProvider?.interface_type || activePreset?.interface_type) === 'antigravity'
                                ? 'agy 命令路径或桥接目录（可选，留空默认使用本机 agy）'
                                : isFlow ? 'Google Flow 网页' : 'API Base URL'}
                        </label>
                        <Input
                            value={formBaseUrl}
                            disabled={isFlow}
                            onChange={setFormBaseUrl}
                            placeholder={
                                (editingProvider?.interface_type || activePreset?.interface_type) === 'antigravity'
                                    ? '留空默认 agy，或填 /usr/local/bin/agy 或桥接目录路径'
                                    : 'https://open.bigmodel.cn/api/coding/paas/v4'
                            }
                        />
                    </div>

                    {!isFlow && (editingProvider?.interface_type || activePreset?.interface_type) !== 'antigravity' && (
                        <div>
                            <label className="block text-[13px] font-medium text-[var(--text-primary)] mb-1">
                                API Key{' '}
                                {editingProvider?.has_api_key && (
                                    <span className="font-mono text-xs text-[var(--text-muted)]">
                                        （已保存 {editingProvider.api_key_masked}，留空保持不变）
                                    </span>
                                )}
                            </label>
                            <Input
                                mode="password"
                                value={formApiKey}
                                onChange={setFormApiKey}
                                placeholder={activePreset?.api_key_placeholder || 'sk-...'}
                            />
                        </div>
                    )}

                    {/* Quick-pick model chips from preset + live /models discovery */}
                    {isFlow && <FlowBrowserPair key={editingProvider?.id || 'new'} providerId={editingProvider?.id}
                        status={providers.find(p => p.id === editingProvider?.id)?.flow_status} />}
                    {!isFlow && (activePreset?.models.length || formModels.length) > 0 && (
                        <div className="space-y-1.5">
                            <div className="text-xs text-[var(--text-muted)]">点击快速填入推荐或已拉取的模型 ID：</div>
                            <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                                {activePreset?.models.map((m) => {
                                    const active = formDefaultModel === m.id
                                    return (
                                        <button
                                            key={m.id}
                                            type="button"
                                            onClick={() => setFormDefaultModel(m.id)}
                                            className="px-2 py-1 rounded-[4px] border text-[11px] font-mono cursor-pointer transition-colors"
                                            style={{
                                                backgroundColor: active ? 'var(--accent-soft)' : 'var(--bg-elevated)',
                                                borderColor: active ? 'var(--accent)' : 'var(--border)',
                                                color: active ? 'var(--accent)' : 'var(--text-primary)',
                                            }}
                                        >
                                            {m.id}
                                            {m.context_window ? ` · ${formatCtx(m.context_window)}` : ''}
                                            {m.supports_vision ? ' · 识图' : ''}
                                            {m.supports_image_gen ? ' · 作图' : ''}
                                        </button>
                                    )
                                })}
                                {formModels
                                    .filter((id) => !(activePreset?.models || []).some((m) => m.id === id))
                                    .slice(0, 24)
                                    .map((id) => {
                                        const active = formDefaultModel === id
                                        return (
                                            <button
                                                key={id}
                                                type="button"
                                                onClick={() => setFormDefaultModel(id)}
                                                className="px-2 py-1 rounded-[4px] border text-[11px] font-mono cursor-pointer transition-colors"
                                                style={{
                                                    backgroundColor: active
                                                        ? 'var(--accent-soft)'
                                                        : 'var(--bg-elevated)',
                                                    borderColor: active ? 'var(--accent)' : 'var(--border)',
                                                    color: active ? 'var(--accent)' : 'var(--text-secondary)',
                                                }}
                                            >
                                                {id}
                                            </button>
                                        )
                                    })}
                            </div>
                        </div>
                    )}

                    {/* Quick Role Activation when creating */}
                    {!editingProvider && !isFlow && (
                        <div className="pt-2 border-t border-[var(--border)] space-y-2">
                            <div className="text-xs font-medium text-[var(--text-primary)]">保存后立即绑定至角色：</div>
                            <div className="flex flex-wrap gap-4">
                                {(
                                    [
                                        { key: 'main_llm', label: '主推理 / 编剧模型' },
                                        { key: 'vision_llm', label: '漫画识图模型' },
                                        { key: 'image_gen', label: '作图引擎' },
                                        { key: 'embedding', label: '向量嵌入' },
                                    ] as const
                                ).map((r) => (
                                    <Checkbox
                                        key={r.key}
                                        checked={activateRoles.includes(r.key)}
                                        onChange={(e) => {
                                            if (e.target.checked) {
                                                setActivateRoles((prev) => [...prev, r.key])
                                            } else {
                                                setActivateRoles((prev) => prev.filter((k) => k !== r.key))
                                            }
                                        }}
                                    >
                                        {r.label}
                                    </Checkbox>
                                ))}
                            </div>
                        </div>
                    )}

                    {testResult && (
                        <div
                            className="rounded-[4px] border px-3 py-2 text-xs font-mono"
                            style={{
                                borderColor: testResult.ok ? 'var(--status-ok)' : 'var(--accent)',
                                backgroundColor: testResult.ok ? 'rgba(74, 222, 128, 0.08)' : 'var(--accent-soft)',
                                color: testResult.ok ? 'var(--status-ok)' : 'var(--accent)',
                            }}
                        >
                            {testResult.ok ? '✓ ' : '✗ '}
                            {testResult.message}
                            {testResult.latency_ms > 0 ? ` (${testResult.latency_ms} ms)` : ''}
                        </div>
                    )}
                </div>
            </Modal>
        </div>
    )
}
