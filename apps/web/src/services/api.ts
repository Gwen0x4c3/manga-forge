import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'
import { Toast } from '@douyinfe/semi-ui'

const instance = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
})

instance.interceptors.response.use(
    (response) => {
        const body = response.data
        if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
            return body.data
        }
        return body
    },
    (error) => {
        const body = error?.response?.data
        const status = error?.response?.status
        const message = (body && typeof body === 'object' && 'message' in body)
            ? String(body.message)
            : (error?.message || 'Unknown error')

        console.error(`API Error [${status}]:`, message)

        Toast.error({ content: message, duration: 5 })

        return Promise.reject(error)
    }
)

const api = {
    get: <T>(url: string, config?: AxiosRequestConfig) => instance.get<never, T>(url, config),
    post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) => instance.post<never, T>(url, data, config),
    patch: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) => instance.patch<never, T>(url, data, config),
    put: <T>(url: string, data?: unknown) => instance.put<never, T>(url, data),
    delete: <T>(url: string) => instance.delete<never, T>(url),
}

export default api
