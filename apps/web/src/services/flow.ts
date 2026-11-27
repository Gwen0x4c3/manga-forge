import api from './api'

export interface FlowAccount {
    id: string
    name: string
    status: 'unpaired' | 'offline' | 'login_required' | 'ready'
    connection_id: string | null
}

export interface FlowOptions {
    model: 'veo-3.1-lite' | 'omni-flash-1.2'
    aspect_ratio: 'landscape' | 'portrait'
    pages_per_clip: 1 | 2
}

export interface FlowPlan {
    plan_id: string
    sources: { key: string; label: string; kind: string }[]
    shots: { label: string; prompt: string; references: string[] }[]
}

export interface FlowRun {
    id: string
    provider_id: string | null
    connection_id: string | null
    mode: 'video' | 'sync'
    status: 'queued' | 'running' | 'succeeded' | 'failed'
    model: string
    synced: number
    sources: number
    completed: number
    clips: number
    project_title: string | null
    remote_id: string | null
    project_url: string | null
    waiting_for: 'upload_rights' | null
    output_key: string | null
    error: string | null
    created_at: string
    legacy: boolean
    uncertain: boolean
}

export const flowService = {
    accounts: () => api.get<FlowAccount[]>('/flow/accounts'),
    plan: (episode: string, options: FlowOptions) => api.post<FlowPlan>(`/flow/episodes/${episode}/plan`, options),
    runs: (episode: string) => api.get<FlowRun[]>(`/flow/episodes/${episode}/runs`),
    start: (episode: string, data: FlowOptions & {
        provider_id: string; connection_id: string; mode: FlowRun['mode']; plan_id: string; prompts?: string[]; request_id?: string
    }) => api.post<FlowRun>(`/flow/episodes/${episode}/runs`, data),
    resume: (episode: string, runId: string, providerId: string, retryUncertain = false) =>
        api.post<FlowRun>(`/flow/episodes/${episode}/runs/${runId}/resume`, undefined, {
            params: { provider_id: providerId, retry_uncertain: retryUncertain },
        }),
}
