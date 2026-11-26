import api from './api'

export interface PaginatedParams {
    page?: number
    page_size?: number
}

export interface MainPlotInfo {
    core_conflict?: string
    current_arc?: string
    protagonist_goal?: string
    arc_progress?: string
    next_hook?: string
}

export interface StoryArcSummary {
    key?: string
    start_episode: string | number
    end_episode: string | number
    count?: number
    sealed?: boolean
    summary: string
}

export interface StoryBible {
    main_plot?: MainPlotInfo
    art_style?: string
    core_rules?: string[]
    discovered_rules?: string[]
    arc_summaries?: StoryArcSummary[]
    last_updated_episode?: string
}

export interface Project {
    id: string
    title: string
    description?: string
    language: string
    canon_rules?: {
        story_bible?: StoryBible
        [key: string]: unknown
    } | null
    long_summary?: string
    cover_image_path?: string | null
    episode_count?: number
    understood_count?: number
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
    canon_rules?: Record<string, unknown>
    long_summary?: string
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
    source_episode_id?: string | null
    target_episode_id?: string | null
    source_status?: string | null
    target_status?: string | null
    title_source?: string | null
    title_target?: string | null
    summary_source?: string | null
    summary_target?: string | null
}

export interface AssetDiffItem {
    asset_id?: string | null
    name: string
    asset_type: string
    in_source: boolean
    in_target: boolean
    description_source?: string | null
    description_target?: string | null
}

export interface PitDiffItem {
    source_pit_id?: string | null
    target_pit_id?: string | null
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
    tags?: {
        visual_tags?: string[]
        aliases?: string[]
        role?: string
        speech_style?: string
        latest_appearance?: string
        latest_state?: string
        context?: string
        [key: string]: unknown
    } | null
    prompt_snippets?: Record<string, unknown> | null
    parent_asset_id?: string | null
    embedding?: number[] | null
    episode_ids?: Record<string, unknown> | null
    preview_image_path?: string | null
    image_count?: number
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

export interface ImportJob {
    id: string
    project_id: string
    branch_id: string
    binding_id?: string | null
    provider: string
    job_type: string
    status: string
    source_url?: string | null
    external_series_id?: string | null
    config?: Record<string, unknown> | null
    metadata_json?: Record<string, unknown> | null
    progress?: Record<string, unknown> | null
    error?: string | null
    started_at?: string | null
    finished_at?: string | null
    created_at: string
    updated_at: string
}

export interface ImportJobItem {
    id: string
    external_chapter_id: string
    chapter_number: string
    sort_number: number
    volume?: string | null
    title?: string | null
    translated_language: string
    group_ids?: string[] | null
    group_names?: string[] | null
    page_count?: number | null
    selection_status: string
    import_status: string
    episode_id?: string | null
    external_url?: string | null
    progress?: Record<string, unknown> | null
    metadata_json?: Record<string, unknown> | null
    error?: string | null
    created_at: string
    updated_at: string
}

export interface MangaDexDiscoverPayload {
    source_url: string
    branch_id: string
    request_curl?: string
    languages?: string[]
    group_ids?: string[]
    fill_project_metadata?: boolean
    overwrite_project_metadata?: boolean
}

export interface MangaDexCreateProjectPayload {
    source_url: string
    request_curl?: string
    languages?: string[]
    group_ids?: string[]
    fill_project_metadata?: boolean
    overwrite_project_metadata?: boolean
}

export interface MangaDexDiscoverResult {
    project: Project
    job: ImportJob
    items: ImportJobItem[]
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

export interface GenerationContext {
    project_title?: string
    language?: string
    language_label?: string
    art_style?: string
    story_bible?: StoryBible
    canon_rules: string
    long_summary: string
    previous_bridge?: {
        episode_number: string
        title?: string
        summary?: string
        ending_state?: {
            location?: string
            time_and_mood?: string
            active_characters?: string[]
            cliffhanger?: string
        }
        key_events?: Array<{ description: string; significance?: string }>
        closing_dialogue?: string[]
    } | null
    recent_episodes: Array<{
        number: number
        label?: string
        title?: string
        summary: string
        events?: Array<{ description: string; significance?: string }>
        state_changes?: Array<{ character: string; attribute: string; before?: string; after: string }>
    }>
    character_dossier?: Array<{
        id: string
        name: string
        role?: string
        vital_status?: 'alive' | 'injured' | 'missing' | 'sealed' | 'deceased' | string
        vital_status_episode?: string | null
        vital_status_note?: string
        description: string
        visual_tags?: string[]
        current_state?: string
        speech_style?: string
        speech_samples?: string[]
    }>
    unavailable_characters?: Array<{
        id: string
        name: string
        vital_status: string
        vital_status_episode?: string | null
        vital_status_note?: string
    }>
    world_assets?: Array<{
        id: string
        type: string
        name: string
        description: string
        visual_tags?: string[]
        latest_state?: string
    }>
    rag_memories: Array<{
        content: string
        episode_number?: number
        type: string
    }>
    active_pits: Array<{
        id?: string
        title?: string
        description: string
        priority: number
        priority_label?: string
        trigger_hint?: string | null
        clues?: string[]
    }>
    assets: Array<{
        id?: string
        type: string
        name: string
        description: string
        visual_tags?: string[]
    }>
    context_budget?: {
        profile: 'quality' | 'balanced' | 'cost' | string
        profile_label: string
        budget_tokens: number
        estimated_tokens_before: number
        estimated_tokens_after: number
        utilization_pct: number
        trimmed: boolean
        trim_actions: string[]
        section_tokens: Record<string, number>
    }
}

export type ContextProfileKey = 'quality' | 'balanced' | 'cost'

export interface GenerationRun {
    id: string
    episode_id: string
    stage: string
    status: string
    backend?: string | null
    model?: string | null
    params?: Record<string, unknown> | null
    retrieved_context?: GenerationContext | null
    error?: string | null
    commit_message?: string | null
    created_at?: string | null
    finished_at?: string | null
}

export interface Storyboard {
    title: string
    synopsis: string
    arc_connection?: string
    addressed_pit_ids?: string[]
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

export interface BubbleCustomBox {
    x_pct?: number
    y_pct?: number
    font_scale?: number
    style?: string
    tail_dir?: string
}

export interface PanelBoxItem {
    panel_id: string
    x_pct: number
    y_pct: number
    w_pct: number
    h_pct: number
}

export interface BubbleLayoutItem {
    panel_id: string
    dialogue_index: number
    speaker: string
    text: string
    style: string
    tail_dir: string
    font_scale: number
    x_pct: number
    y_pct: number
    w_pct: number
    h_pct: number
    page_x_pct: number
    page_y_pct: number
    page_w_pct: number
    page_h_pct: number
}

export interface ComposedPage {
    page_number: number
    image_path: string
    layout: string
    writing_mode?: string
    panel_boxes?: PanelBoxItem[]
    bubble_layouts?: BubbleLayoutItem[]
}

export interface StoryboardPanel {
    panel_id: string
    scene: string
    location?: string
    items?: string[]
    characters: { name: string; outfit?: string; emotion?: string; posture?: string }[]
    camera: string
    mood?: string
    dialogue: {
        speaker: string
        text: string
        type: string
        speaker_position?: string
        custom_box?: BubbleCustomBox
    }[]
    prompt: string
    negative_prompt?: string
}

export interface StoryGraphCharacterNode {
    id: string
    name: string
    role: string
    vital_status?: 'alive' | 'injured' | 'missing' | 'sealed' | 'deceased' | string
    vital_status_episode?: string | null
    vital_status_note?: string
    vital_status_override?: string | null
    aliases: string[]
    description: string
    speech_style: string
    visual_tags: string[]
    avatar_path: string | null
    appearances: number
    episode_numbers: number[]
    state_timeline: Array<{
        episode_number: number
        episode_label: string
        attribute: string
        before?: string
        after: string
    }>
    outfits: Array<{
        id: string
        name: string
        description: string
        image_path: string | null
    }>
}

export interface StoryGraphEdge {
    source: string
    target: string
    weight: number
    shared_episodes: number[]
    moments: Array<{
        episode_number: number
        episode_label: string
        description: string
        location: string
        significance: string
    }>
}

export interface StoryTimelineEpisode {
    id: string
    number: number
    label: string
    title: string
    source: string
    status: string
    cover_path: string | null
    summary: string
    event_count: number
    major_events: Array<{
        description: string
        significance: string
        location?: string | null
        characters: string[]
    }>
    cliffhanger: string
}

export interface StoryPitSwimlane {
    id: string
    title: string
    description: string
    status: string
    priority: number
    trigger_hint?: string | null
    introduced_episode_number: number | null
    introduced_episode_label: string | null
    resolved_episode_number: number | null
    resolved_episode_label: string | null
    clues: Array<{ episode_number: number | null; text: string }>
}

export interface StoryBranchTreeNode {
    id: string
    name: string
    description: string
    is_default: boolean
    base_branch_id?: string | null
    base_episode_id?: string | null
    episode_count: number
    episodes: Array<{
        id: string
        number: number
        label: string
        title: string
        source: string
        status: string
        parent_episode_id?: string | null
        cover_path: string | null
    }>
}

export interface StoryGraphResponse {
    project_id: string
    project_title: string
    branch_id: string
    branch_name: string
    story_bible: StoryBible
    character_graph: {
        nodes: StoryGraphCharacterNode[]
        edges: StoryGraphEdge[]
    }
    timeline: {
        episodes: StoryTimelineEpisode[]
        arcs: StoryArcSummary[]
        pit_swimlanes: StoryPitSwimlane[]
    }
    branch_tree: StoryBranchTreeNode[]
}

export interface StoryBibleQAResponse {
    question: string
    answer: string
    model: string
    citations: Array<{
        episode_id: string
        episode_number: number | null
        episode_label: string
        title: string
        type: string
        excerpt: string
        page_image_path: string | null
        score: number
    }>
    matched_characters: Array<{
        id: string
        name: string
        role: string
        avatar_path: string | null
    }>
}

export interface AssetImage {
    id: string
    asset_id: string
    kind: string
    image_path: string
    meta: Record<string, unknown> | null
    created_at: string
}

export function storageFileUrl(objectKey?: string | null): string {
    if (!objectKey) return ''
    return `/api/v1/storage/file/${objectKey}`
}

export const projectService = {
    list: (keyword?: string, pagination?: PaginatedParams) =>
        api.get<{ items: Project[]; total: number }>('/projects', { params: { keyword, ...pagination } }),
    get: (id: string) => api.get<Project>(`/projects/${id}`),
    create: (data: CreateProjectRequest) => api.post<Project>('/projects', data),
    update: (id: string, data: UpdateProjectRequest) => api.put<Project>(`/projects/${id}`, data),
    delete: (id: string) => api.delete(`/projects/${id}`),
}

export const importService = {
    createProjectFromMangaDex: (data: MangaDexCreateProjectPayload) =>
        api.post<MangaDexDiscoverResult>('/imports/mangadex/projects/discover', data, { timeout: 180000 }),
    discoverForProject: (projectId: string, data: MangaDexDiscoverPayload) =>
        api.post<MangaDexDiscoverResult>(`/imports/projects/${projectId}/mangadex/discover`, data, { timeout: 180000 }),
    listJobs: (projectId: string) =>
        api.get<{ items: ImportJob[]; total: number }>(`/imports/projects/${projectId}/jobs`),
    getJob: (projectId: string, jobId: string) =>
        api.get<ImportJob>(`/imports/projects/${projectId}/jobs/${jobId}`),
    listItems: (projectId: string, jobId: string) =>
        api.get<ImportJobItem[]>(`/imports/projects/${projectId}/jobs/${jobId}/items`),
    updateSelection: (projectId: string, jobId: string, data: { item_ids: string[]; action: 'select' | 'unselect' }) =>
        api.patch<MangaDexDiscoverResult>(`/imports/projects/${projectId}/jobs/${jobId}/selection`, data),
    startJob: (
        projectId: string,
        jobId: string,
        data: { auto_understand?: boolean; only_missing?: boolean; use_data_saver?: boolean; request_curl?: string },
    ) => api.post<{ job: ImportJob; task_id: string }>(`/imports/projects/${projectId}/jobs/${jobId}/start`, data),
    resumeJob: (projectId: string, jobId: string, data?: { request_curl?: string }) =>
        api.post<{ job: ImportJob; task_id: string }>(`/imports/projects/${projectId}/jobs/${jobId}/resume`, data),
    pauseJob: (projectId: string, jobId: string) =>
        api.post<ImportJob>(`/imports/projects/${projectId}/jobs/${jobId}/pause`),
}

export const branchService = {
    list: (projectId: string) => api.get<Branch[]>(`/projects/${projectId}/branches`),
    create: (projectId: string, data: { name: string; description?: string }) =>
        api.post<Branch>(`/projects/${projectId}/branches`, data),
    get: (branchId: string) => api.get<Branch>(`/projects/branches/${branchId}`),
    delete: (branchId: string) => api.delete(`/projects/branches/${branchId}`),
    fork: (projectId: string, data: { episode_id: string; branch_name: string; description?: string }) =>
        api.post<Branch>(`/projects/${projectId}/branches/fork`, data),
    diff: (projectId: string, data: { source_branch_id: string; target_branch_id: string; episode_number?: number }) =>
        api.post<DiffResponse>(`/projects/${projectId}/branches/diff`, data),
    merge: (projectId: string, data: { source_branch_id: string; target_branch_id: string; items: MergeItem[] }) =>
        api.post<MergeResponse>(`/projects/${projectId}/branches/merge`, data),
}

export const episodeService = {
    list: (projectId: string, branchId?: string, pagination?: PaginatedParams) =>
        api.get<{ items: Episode[]; total: number }>(`/projects/${projectId}/episodes`, {
            params: { branch_id: branchId, ...pagination },
        }),
    get: (episodeId: string) => api.get<Episode>(`/projects/episodes/${episodeId}`),
    update: (episodeId: string, data: { title?: string; status?: string; category?: string; label?: string }) =>
        api.put<Episode>(`/projects/episodes/${episodeId}`, data),
    import: (projectId: string, data: ImportEpisodeRequest) =>
        api.post<Episode>(`/projects/${projectId}/episodes/import`, data),
    importFiles: (projectId: string, formData: FormData) =>
        api.post<Episode>(`/projects/${projectId}/episodes/import-files`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 180000,
        }),
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
        return api.post<{ object_key: string; bucket: string }>('/storage/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
    },
}

export const assetService = {
    list: (projectId: string, type?: string, pagination?: PaginatedParams) =>
        api.get<{ items: Asset[]; total: number }>(`/projects/${projectId}/assets`, {
            params: { type, ...pagination },
        }),
    get: (assetId: string) => api.get<Asset>(`/projects/assets/${assetId}`),
    create: (projectId: string, data: AssetCreateRequest) =>
        api.post<Asset>(`/projects/${projectId}/assets`, data),
    update: (assetId: string, data: AssetUpdateRequest) =>
        api.put<Asset>(`/projects/assets/${assetId}`, data),
    delete: (assetId: string) => api.delete(`/projects/assets/${assetId}`),
    cluster: (projectId: string, type?: string) =>
        api.post<AssetClusterResponse>(`/projects/${projectId}/assets/cluster`, null, { params: { type } }),
    merge: (projectId: string, data: AssetMergeRequest) =>
        api.post<Asset>(`/projects/${projectId}/assets/merge`, data),
    findSimilar: (assetId: string) => api.get<AssetClusterItem[]>(`/projects/assets/${assetId}/similar`),
    vectorize: (assetId: string) => api.post<Asset>(`/projects/assets/${assetId}/vectorize`),
}

export const memoryService = {
    getCanonRules: (projectId: string) =>
        api.get<{ canon_rules: Record<string, unknown> | null }>(`/projects/${projectId}/memory/canon`),
    updateCanonRules: (projectId: string, canonRules: Record<string, unknown>) =>
        api.put<{ canon_rules: Record<string, unknown> }>(`/projects/${projectId}/memory/canon`, canonRules),
    getLongSummary: (projectId: string) =>
        api.get<{ long_summary: string | null }>(`/projects/${projectId}/memory/summary`),
    updateLongSummary: (projectId: string, longSummary: string) =>
        api.put<{ long_summary: string }>(`/projects/${projectId}/memory/summary`, { long_summary: longSummary }),
    getRecentWindow: (projectId: string, branchId: string, windowSize?: number) =>
        api.get<{
            episodes: Array<{ episode_id: string; number: number; title?: string; summary: Record<string, unknown> | null }>
        }>(`/projects/${projectId}/memory/recent`, { params: { branch_id: branchId, window_size: windowSize } }),
    searchRag: (projectId: string, query: string, topK?: number) =>
        api.post<{ results: Array<{ id: string; score: number; payload: Record<string, unknown> }>; query: string }>(
            `/projects/${projectId}/memory/search`,
            null,
            { params: { query, top_k: topK } },
        ),
    getGenerationContext: (
        projectId: string,
        branchId: string,
        baseEpisodeNumber: number,
        options?: { custom_instructions?: string; context_profile?: ContextProfileKey },
    ) =>
        api.get<GenerationContext>(`/projects/${projectId}/memory/context`, {
            params: {
                branch_id: branchId,
                base_episode_number: baseEpisodeNumber,
                custom_instructions: options?.custom_instructions || undefined,
                context_profile: options?.context_profile || undefined,
            },
        }),
    getGraph: (projectId: string, branchId?: string) =>
        api.get<StoryGraphResponse>(`/projects/${projectId}/memory/graph`, {
            params: branchId ? { branch_id: branchId } : undefined,
        }),
    askBible: (
        projectId: string,
        data: { question: string; branch_id?: string; max_episode_number?: number },
    ) => api.post<StoryBibleQAResponse>(`/projects/${projectId}/memory/ask`, data, { timeout: 120000 }),
}

export const generationService = {
    triggerUnderstand: (episodeId: string) =>
        api.post<{ task_id: string; episode_id: string; status: string }>('/generation/understand', {
            episode_id: episodeId,
        }),
    triggerBatchUnderstand: (data: { project_id: string; branch_id?: string; force?: boolean }) =>
        api.post<{
            task_id: string
            project_id: string
            branch_id: string
            episode_ids: string[]
            total: number
            status: string
        }>('/generation/understand-batch', data),
    triggerScriptGeneration: (data: {
        episode_id: string
        branch_id: string
        base_episode_number: number
        tone?: string
        custom_instructions?: string
        context_profile?: ContextProfileKey
    }) => api.post<{ task_id: string; episode_id: string; status: string }>('/generation/script', data),
    updateStoryboard: (episodeId: string, storyboard: Storyboard) =>
        api.put<{ id: string; episode_id: string; storyboard: Storyboard }>(
            `/generation/episodes/${episodeId}/storyboard`,
            { storyboard },
        ),
    triggerRender: (data: {
        episode_id: string
        storyboard_memory_id?: string
        image_backend?: string
        image_model?: string
        image_size?: string
    }) => api.post<{ task_id: string; episode_id: string; status: string; panel_count: number }>('/generation/render', data),
    rerenderPanel: (
        episodeId: string,
        panelId: string,
        data: {
            prompt?: string
            negative_prompt?: string
            reference_asset_ids?: string[]
            image_backend?: string
            image_model?: string
            image_size?: string
        },
    ) =>
        api.post<GeneratedImage>(`/generation/episodes/${episodeId}/panels/${panelId}/rerender`, data, {
            timeout: 180000,
        }),
    selectPanelCandidate: (episodeId: string, panelId: string, imageId: string) =>
        api.post<GeneratedImage>(`/generation/episodes/${episodeId}/panels/${panelId}/select/${imageId}`),
    inpaintPanel: (
        episodeId: string,
        panelId: string,
        data: { prompt: string; mask_base64: string; image_backend?: string; image_model?: string },
    ) =>
        api.post<GeneratedImage>(`/generation/episodes/${episodeId}/panels/${panelId}/inpaint`, data, {
            timeout: 180000,
        }),
    triggerLayout: (data: {
        episode_id: string
        template_override?: Record<number, string>
        writing_mode?: 'horizontal' | 'vertical'
        sync?: boolean
    }) =>
        api.post<{
            task_id: string
            episode_id: string
            status: string
            page_count: number
            pages?: ComposedPage[]
        }>('/generation/layout', data, { timeout: 120000 }),
    triggerContinue: (data: {
        project_id: string
        branch_id: string
        base_episode_number: number
        tone?: string
        custom_instructions?: string
        title?: string
        image_backend?: string
        image_model?: string
        image_size?: string
        context_profile?: ContextProfileKey
    }) => api.post<{ episode_id: string; episode_number: number; task_id: string; status: string }>('/generation/continue', data),
    getRun: (runId: string) => api.get<GenerationRun>(`/generation/runs/${runId}`),
    listEpisodeRuns: (episodeId: string) => api.get<{ items: GenerationRun[] }>(`/generation/episodes/${episodeId}/runs`),
    getGeneratedImages: (episodeId: string, includeCandidates: boolean = false) =>
        api.get<{ items: GeneratedImage[] }>(`/generation/episodes/${episodeId}/images`, {
            params: includeCandidates ? { include_candidates: true } : undefined,
        }),
    getLayoutResult: (episodeId: string) =>
        api.get<{ pages: ComposedPage[] }>(`/generation/episodes/${episodeId}/layout`),
}

export const pitService = {
    list: (projectId: string, status?: string, pagination?: PaginatedParams) =>
        api.get<{ items: Pit[]; total: number }>(`/projects/${projectId}/pits`, { params: { status, ...pagination } }),
    create: (
        projectId: string,
        data: { title: string; description?: string; priority?: number; introduced_episode_id: string; trigger_hint?: string },
    ) => api.post<Pit>(`/projects/${projectId}/pits`, data),
    update: (
        pitId: string,
        data: { title?: string; description?: string; priority?: number; status?: string; trigger_hint?: string },
    ) => api.put<Pit>(`/projects/pits/${pitId}`, data),
    resolve: (pitId: string, resolvedEpisodeId: string) =>
        api.post<Pit>(`/projects/pits/${pitId}/resolve`, null, { params: { resolved_episode_id: resolvedEpisodeId } }),
}

export const assetImageService = {
    list: (assetId: string) => api.get<{ items: AssetImage[] }>(`/projects/assets/${assetId}/images`),
    upload: (assetId: string, file: File, kind: string = 'reference') => {
        const formData = new FormData()
        formData.append('file', file)
        formData.append('kind', kind)
        return api.post<AssetImage>(`/projects/assets/${assetId}/images`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
    },
    cropFromPage: (
        assetId: string,
        data: { episode_id: string; page_index: number; bbox: [number, number, number, number]; kind?: string },
    ) => api.post<AssetImage>(`/projects/assets/${assetId}/crop-from-page`, data),
    remove: (imageId: string) => api.delete(`/projects/asset-images/${imageId}`),
}

export interface UsageTotals {
    total_calls: number
    llm_calls: number
    embedding_calls: number
    image_calls: number
    failed_calls: number
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    total_tokens: number
    cache_hit_rate: number
    total_images: number
    total_duration_ms: number
    avg_llm_duration_ms: number
    avg_image_duration_ms: number
}

export interface UsageByModelItem {
    kind: string
    provider: string
    model: string
    calls: number
    failed_calls: number
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    total_tokens: number
    cache_hit_rate: number
    image_count: number
    avg_duration_ms: number
    total_duration_ms: number
}

export interface UsageByOperationItem {
    operation: string
    kind: string
    calls: number
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    total_tokens: number
    cache_hit_rate: number
    image_count: number
    avg_duration_ms: number
}

export interface UsageDailyItem {
    date: string
    llm_calls: number
    image_calls: number
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    total_tokens: number
    image_count: number
}

export interface UsageSummaryResponse {
    totals: UsageTotals
    by_model: UsageByModelItem[]
    by_operation: UsageByOperationItem[]
    daily: UsageDailyItem[]
}

export interface UsageRecordItem {
    id: string
    project_id?: string | null
    project_title?: string | null
    episode_id?: string | null
    episode_label?: string | null
    generation_run_id?: string | null
    kind: 'llm' | 'embedding' | 'image' | string
    operation: string
    provider: string
    model: string
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    total_tokens: number
    cache_hit_rate: number
    image_count: number
    image_size?: string | null
    duration_ms: number
    status: string
    error?: string | null
    meta?: Record<string, unknown> | null
    created_at: string
}

export interface UsageRecordListResponse {
    items: UsageRecordItem[]
    total: number
    page: number
    page_size: number
}

export const usageService = {
    summary: (params?: { project_id?: string; episode_id?: string; days?: number }) =>
        api.get<UsageSummaryResponse>('/usage/summary', { params }),
    records: (params?: {
        project_id?: string
        episode_id?: string
        kind?: string
        model?: string
        operation?: string
        status?: string
        page?: number
        page_size?: number
    }) => api.get<UsageRecordListResponse>('/usage/records', { params }),
}

export interface ModelPresetInfo {
    id: string
    label: string
    context_window?: number | null
    supports_vision: boolean
    supports_tools: boolean
    supports_image_gen: boolean
    supports_embedding: boolean
}

export interface ProviderPreset {
    key: string
    name: string
    category: 'aggregator' | 'global' | 'china' | 'image' | 'custom' | string
    interface_type: string
    base_url: string
    default_model: string
    description: string
    requires_api_key: boolean
    supports_llm: boolean
    supports_vision: boolean
    supports_image: boolean
    supports_embedding: boolean
    api_key_placeholder: string
    docs_url: string
    extra_headers: Record<string, string>
    models: ModelPresetInfo[]
}

export interface ModelProviderItem {
    id: string
    preset_key: string
    name: string
    interface_type: string
    base_url: string
    has_api_key: boolean
    api_key_masked: string
    default_model: string
    models_cache: string[]
    extra_headers: Record<string, string>
    enabled: boolean
    last_test_status?: string | null
    last_test_message?: string | null
    last_tested_at?: string | null
    created_at: string
    updated_at: string
}

export interface RoleBindingItem {
    role: 'main_llm' | 'vision_llm' | 'image_gen' | 'embedding' | string
    provider_id?: string | null
    provider_name?: string | null
    preset_key?: string | null
    model_id?: string | null
    params: Record<string, unknown>
    effective_source: 'database' | 'env' | string
    effective_provider: string
    effective_model: string
    effective_base_url?: string | null
}

export interface ProviderOverviewResponse {
    presets: ProviderPreset[]
    providers: ModelProviderItem[]
    roles: RoleBindingItem[]
}

export interface ProviderTestResponse {
    ok: boolean
    latency_ms: number
    message: string
    models: string[]
}

export const providerService = {
    overview: () => api.get<ProviderOverviewResponse>('/providers'),
    create: (data: {
        preset_key: string
        name: string
        interface_type?: string
        base_url?: string
        api_key?: string
        default_model?: string
        models_cache?: string[]
        extra_headers?: Record<string, string>
        enabled?: boolean
        activate_roles?: string[]
    }) => api.post<ModelProviderItem>('/providers', data),
    update: (
        providerId: string,
        data: {
            name?: string
            interface_type?: string
            base_url?: string
            api_key?: string
            default_model?: string
            models_cache?: string[]
            extra_headers?: Record<string, string>
            enabled?: boolean
        },
    ) => api.put<ModelProviderItem>(`/providers/${providerId}`, data),
    remove: (providerId: string) => api.delete(`/providers/${providerId}`),
    test: (data: {
        provider_id?: string
        preset_key?: string
        interface_type?: string
        base_url?: string
        api_key?: string
        model?: string
        extra_headers?: Record<string, string>
    }) => api.post<ProviderTestResponse>('/providers/test', data, { timeout: 30000 }),
    updateRole: (
        role: string,
        data: { provider_id?: string | null; model_id?: string | null; params?: Record<string, unknown> },
    ) => api.put<RoleBindingItem>(`/providers/roles/${role}`, data),
}
