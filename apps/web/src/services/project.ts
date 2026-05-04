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
