import { create } from 'zustand'

export type StudioTheme = 'dark' | 'light'

function getInitialTheme(): StudioTheme {
    if (typeof window === 'undefined') return 'dark'
    const stored = window.localStorage.getItem('mf-theme')
    return stored === 'light' ? 'light' : 'dark'
}

export function applyThemeToDom(theme: StudioTheme) {
    if (typeof document === 'undefined') return
    document.documentElement.setAttribute('data-theme', theme)
    if (theme === 'dark') {
        document.body.setAttribute('theme-mode', 'dark')
    } else {
        document.body.removeAttribute('theme-mode')
    }
}

interface AppState {
    theme: StudioTheme
    sidebarCollapsed: boolean
    inspectorOpen: boolean
    inspectorWidth: number
    setTheme: (theme: StudioTheme) => void
    toggleTheme: () => void
    toggleSidebar: () => void
    setSidebarCollapsed: (v: boolean) => void
    toggleInspector: () => void
    setInspectorOpen: (v: boolean) => void
    setInspectorWidth: (w: number) => void
}

const initialTheme = getInitialTheme()
applyThemeToDom(initialTheme)

export const useAppStore = create<AppState>((set) => ({
    theme: initialTheme,
    sidebarCollapsed: false,
    inspectorOpen: true,
    inspectorWidth: 330,
    setTheme: (theme) => {
        if (typeof window !== 'undefined') window.localStorage.setItem('mf-theme', theme)
        applyThemeToDom(theme)
        set({ theme })
    },
    toggleTheme: () =>
        set((state) => {
            const next: StudioTheme = state.theme === 'dark' ? 'light' : 'dark'
            if (typeof window !== 'undefined') window.localStorage.setItem('mf-theme', next)
            applyThemeToDom(next)
            return { theme: next }
        }),
    toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
    toggleInspector: () => set((state) => ({ inspectorOpen: !state.inspectorOpen })),
    setInspectorOpen: (v) => set({ inspectorOpen: v }),
    setInspectorWidth: (w) => set({ inspectorWidth: Math.max(260, Math.min(500, w)) }),
}))
