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
    base_branch_id?: string
    base_episode_id?: string
    created_at: string
    updated_at: string
}

export interface Episode {
    id: string
    project_id: string
    branch_id: string
    number: number
    title?: string
    source: string
    status: string
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
    title?: string
    source?: string
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
    create: (projectId: string, data: { name: string }) => api.post<Branch>(`/projects/${projectId}/branches`, data),
    get: (branchId: string) => api.get<Branch>(`/branches/${branchId}`),
}

export const episodeService = {
    list: (projectId: string, branchId?: string) => api.get<{ items: Episode[]; total: number }>(`/projects/${projectId}/episodes`, { params: { branch_id: branchId } }),
    get: (episodeId: string) => api.get<Episode>(`/episodes/${episodeId}`),
    import: (projectId: string, data: ImportEpisodeRequest) => api.post<Episode>(`/projects/${projectId}/episodes/import`, data),
    importFiles: (projectId: string, formData: FormData) => api.post<Episode>(`/projects/${projectId}/episodes/import-files`, formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
    getPages: (episodeId: string) => api.get<EpisodePage[]>(`/episodes/${episodeId}/pages`),
    getMemories: (episodeId: string) => api.get<EpisodeMemory[]>(`/episodes/${episodeId}/memories`),
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
    error?: string | null
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
    getRun: (runId: string) => api.get<GenerationRun>(`/generation/runs/${runId}`),
    listEpisodeRuns: (episodeId: string) => api.get<{ items: GenerationRun[] }>(`/generation/episodes/${episodeId}/runs`),
}
