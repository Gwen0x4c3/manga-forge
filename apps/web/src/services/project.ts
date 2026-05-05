import api from './api'

export interface Project {
    id: string
    title: string
    description?: string
    language: string
    canon_rules?: Record<string, unknown>
    long_summary?: string
    created_at: string
    updated_at: string
}

export interface CreateProjectRequest {
    title: string
    description?: string
    language?: string
}

export interface UpdateProjectRequest {
    title?: string
    description?: string
    language?: string
}

export interface Branch {
    id: string
    project_id: string
    name: string
    description?: string
    is_default: boolean
    base_branch_id?: string
    base_episode_id?: string
    created_at: string
    updated_at: string
    episode_count?: number
    latest_episode_number?: number | null
}

export interface EpisodeDiffItem {
    number: number
    label: string
    source_status?: string | null
    target_status?: string | null
    title_source?: string | null
    title_target?: string | null
    summary_source?: string | null
    summary_target?: string | null
}

export interface AssetDiffItem {
    name: string
    asset_type: string
    in_source: boolean
    in_target: boolean
    description_source?: string | null
    description_target?: string | null
}

export interface PitDiffItem {
    title: string
    status_source?: string | null
    status_target?: string | null
}

export interface DiffResponse {
    episodes: EpisodeDiffItem[]
    assets: AssetDiffItem[]
    pits: PitDiffItem[]
    canon_diff: Record<string, unknown> | null
}

export interface MergeItem {
    item_type: 'episode' | 'asset' | 'pit' | 'canon_rule'
    source_id: string
    action: 'adopt' | 'skip'
}

export interface MergeResponse {
    merged_items: string[]
    skipped_items: string[]
    errors: string[]
}

export interface Asset {
    id: string
    project_id: string
    type: string
    name: string
    description?: string | null
    tags?: Record<string, unknown> | null
    prompt_snippets?: Record<string, unknown> | null
    parent_asset_id?: string | null
    embedding?: number[] | null
    episode_ids?: Record<string, unknown> | null
    created_at: string
    updated_at: string
}

export interface AssetCreateRequest {
    type: string
    name: string
    description?: string
    tags?: Record<string, unknown>
    prompt_snippets?: Record<string, unknown>
    parent_asset_id?: string
}

export interface AssetUpdateRequest {
    name?: string
    description?: string
    tags?: Record<string, unknown>
    prompt_snippets?: Record<string, unknown>
}

export interface AssetClusterItem {
    asset_id: string
    name: string
    asset_type: string
    similarity: number
}

export interface AssetClusterGroup {
    representative_name: string
    asset_type: string
    items: AssetClusterItem[]
}

export interface AssetClusterResponse {
    clusters: AssetClusterGroup[]
    total_assets: number
    unclustered: number
}

export interface AssetMergeRequest {
    source_asset_ids: string[]
    target_name: string
    target_description?: string
}

export interface Episode {
    id: string
    project_id: string
    branch_id: string
    number: number
    label: string
    title?: string
    source: string
    status: string
    category: string
    parent_episode_id?: string
    created_at: string
    updated_at: string
}

export interface EpisodePage {
    id: string
    episode_id: string
    page_index: number
    image_path: string
    width?: number
    height?: number
    created_at: string
}

export interface ImportEpisodeRequest {
    branch_id: string
    number: number
    label?: string
    title?: string
    source?: string
    category?: string
}

export const projectService = {
    list: (keyword?: string) => api.get<{ items: Project[]; total: number }>('/projects', { params: { keyword } }),
    get: (id: string) => api.get<Project>(`/projects/${id}`),
    create: (data: CreateProjectRequest) => api.post<Project>('/projects', data),
    update: (id: string, data: UpdateProjectRequest) => api.put<Project>(`/projects/${id}`, data),
    delete: (id: string) => api.delete(`/projects/${id}`),
}

export const branchService = {
    list: (projectId: string) => api.get<Branch[]>(`/projects/${projectId}/branches`),
    create: (projectId: string, data: { name: string; description?: string }) => api.post<Branch>(`/projects/${projectId}/branches`, data),
    get: (branchId: string) => api.get<Branch>(`/branches/${branchId}`),
    delete: (branchId: string) => api.delete(`/branches/${branchId}`),
    fork: (projectId: string, data: { episode_id: string; branch_name: string; description?: string }) => api.post<Branch>(`/projects/${projectId}/branches/fork`, data),
    diff: (projectId: string, data: { source_branch_id: string; target_branch_id: string; episode_number?: number }) => api.post<DiffResponse>(`/projects/${projectId}/branches/diff`, data),
    merge: (projectId: string, data: { source_branch_id: string; target_branch_id: string; items: MergeItem[] }) => api.post<MergeResponse>(`/projects/${projectId}/branches/merge`, data),
}

export const episodeService = {
    list: (projectId: string, branchId?: string) => api.get<{ items: Episode[]; total: number }>(`/projects/${projectId}/episodes`, { params: { branch_id: branchId } }),
    get: (episodeId: string) => api.get<Episode>(`/projects/episodes/${episodeId}`),
    import: (projectId: string, data: ImportEpisodeRequest) => api.post<Episode>(`/projects/${projectId}/episodes/import`, data),
    importFiles: (projectId: string, formData: FormData) => api.post<Episode>(`/projects/${projectId}/episodes/import-files`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
    delete: (episodeId: string) => api.delete(`/projects/episodes/${episodeId}`),
    getPages: (episodeId: string) => api.get<EpisodePage[]>(`/projects/episodes/${episodeId}/pages`),
    getMemories: (episodeId: string) => api.get<EpisodeMemory[]>(`/projects/episodes/${episodeId}/memories`),
}

export const storageService = {
    getFileUrl: (bucket: string, key: string) => api.get<{ url: string }>(`/storage/${bucket}/${key}`),
    upload: (file: File, bucket?: string, prefix?: string) => {
        const formData = new FormData()
        formData.append('file', file)
        if (bucket) formData.append('bucket', bucket)
        if (prefix) formData.append('prefix', prefix)
        return api.post<{ object_key: string; bucket: string }>('/storage/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    },
}

export const assetService = {
    list: (projectId: string, type?: string) => api.get<{ items: Asset[]; total: number }>(`/projects/${projectId}/assets`, { params: { type } }),
    get: (assetId: string) => api.get<Asset>(`/projects/assets/${assetId}`),
    create: (projectId: string, data: AssetCreateRequest) => api.post<Asset>(`/projects/${projectId}/assets`, data),
    update: (assetId: string, data: AssetUpdateRequest) => api.put<Asset>(`/projects/assets/${assetId}`, data),
    delete: (assetId: string) => api.delete(`/projects/assets/${assetId}`),
    cluster: (projectId: string, type?: string) => api.post<AssetClusterResponse>(`/projects/${projectId}/assets/cluster`, null, { params: { type } }),
    merge: (projectId: string, data: AssetMergeRequest) => api.post<Asset>(`/projects/${projectId}/assets/merge`, data),
    findSimilar: (assetId: string) => api.get<AssetClusterItem[]>(`/projects/assets/${assetId}/similar`),
    vectorize: (assetId: string) => api.post<{ message: string }>(`/projects/assets/${assetId}/vectorize`),
}

export interface Pit {
    id: string
    project_id: string
    title: string
    description?: string
    priority: number
    introduced_episode_id: string
    resolved_episode_id?: string
    status: string
    trigger_hint?: string
    created_at: string
    updated_at: string
}

export interface EpisodeMemory {
    id: string
    episode_id: string
    type: string
    content: Record<string, unknown>
    created_at: string
}

export interface GenerationRun {
    id: string
    episode_id: string
    stage: string
    status: string
    backend?: string | null
    model?: string | null
    error?: string | null
    commit_message?: string | null
    created_at?: string | null
    finished_at?: string | null
}

export interface Storyboard {
    title: string
    synopsis: string
    tone: string
    pages: StoryboardPage[]
}

export interface StoryboardPage {
    page_number: number
    layout: string
    panels: StoryboardPanel[]
}

export interface GeneratedImage {
    id: string
    generation_run_id: string
    episode_id: string
    panel_id: string | null
    image_path: string
    meta: Record<string, unknown> | null
    created_at: string | null
}

export interface ComposedPage {
    page_number: number
    image_path: string
    layout: string
}

export interface StoryboardPanel {
    panel_id: string
    scene: string
    characters: { name: string; outfit?: string; emotion?: string; posture?: string }[]
    camera: string
    mood?: string
    dialogue: { speaker: string; text: string; type: string }[]
    prompt: string
    negative_prompt?: string
}

export const memoryService = {
    getCanonRules: (projectId: string) => api.get<{ canon_rules: Record<string, unknown> | null }>(`/projects/${projectId}/memory/canon`),
    updateCanonRules: (projectId: string, canonRules: Record<string, unknown>) => api.put<{ canon_rules: Record<string, unknown> }>(`/projects/${projectId}/memory/canon`, canonRules),
    getLongSummary: (projectId: string) => api.get<{ long_summary: string | null }>(`/projects/${projectId}/memory/summary`),
    getRecentWindow: (projectId: string, branchId: string, windowSize?: number) => api.get<{ episodes: Array<{ episode_id: string; number: number; title?: string; summary: Record<string, unknown> | null }> }>(`/projects/${projectId}/memory/recent`, { params: { branch_id: branchId, window_size: windowSize } }),
    searchRag: (projectId: string, query: string, topK?: number) => api.post<{ results: Array<{ id: string; score: number; payload: Record<string, unknown> }>; query: string }>(`/projects/${projectId}/memory/search`, null, { params: { query, top_k: topK } }),
}

export const generationService = {
    triggerUnderstand: (episodeId: string) => api.post<{ task_id: string; episode_id: string; status: string }>('/generation/understand', { episode_id: episodeId }),
    triggerScriptGeneration: (data: { episode_id: string; branch_id: string; base_episode_number: number; tone?: string; custom_instructions?: string }) => api.post<{ task_id: string; episode_id: string; status: string }>('/generation/script', data),
    triggerRender: (data: { episode_id: string; storyboard_memory_id?: string; image_backend?: string; image_model?: string; image_size?: string }) => api.post<{ task_id: string; episode_id: string; status: string; panel_count: number }>('/generation/render', data),
    triggerLayout: (data: { episode_id: string; template_override?: Record<number, string> }) => api.post<{ task_id: string; episode_id: string; status: string; page_count: number }>('/generation/layout', data),
    triggerContinue: (data: {
        project_id: string;
        branch_id: string;
        base_episode_number: number;
        tone?: string;
        custom_instructions?: string;
        title?: string;
        image_backend?: string;
        image_model?: string;
        image_size?: string;
    }) => api.post<{ episode_id: string; episode_number: number; task_id: string; status: string }>('/generation/continue', data),
    getRun: (runId: string) => api.get<GenerationRun>(`/generation/runs/${runId}`),
    listEpisodeRuns: (episodeId: string) => api.get<{ items: GenerationRun[] }>(`/generation/episodes/${episodeId}/runs`),
    getGeneratedImages: (episodeId: string) => api.get<{ items: GeneratedImage[] }>(`/generation/episodes/${episodeId}/images`),
    getLayoutResult: (episodeId: string) => api.get<{ pages: ComposedPage[] }>(`/generation/episodes/${episodeId}/layout`),
}

export const pitService = {
    list: (projectId: string, status?: string) => api.get<{ items: Pit[]; total: number }>(`/projects/${projectId}/pits`, { params: { status } }),
    create: (projectId: string, data: { title: string; description?: string; priority?: number; introduced_episode_id: string; trigger_hint?: string }) => api.post<Pit>(`/projects/${projectId}/pits`, data),
    update: (pitId: string, data: { title?: string; description?: string; priority?: number; status?: string; trigger_hint?: string }) => api.put<Pit>(`/pits/${pitId}`, data),
    resolve: (pitId: string, resolvedEpisodeId: string) => api.post<Pit>(`/pits/${pitId}/resolve`, null, { params: { resolved_episode_id: resolvedEpisodeId } }),
}
