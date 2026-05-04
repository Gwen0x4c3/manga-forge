import axios from 'axios'
import type { AxiosRequestConfig } from 'axios'

const instance = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
})

instance.interceptors.response.use(
    (response) => response.data,
    (error) => {
        console.error('API Error:', error.response?.data || error.message)
        return Promise.reject(error)
    }
)

const api = {
    get: <T>(url: string, config?: AxiosRequestConfig) => instance.get<never, T>(url, config),
    post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) => instance.post<never, T>(url, data, config),
    put: <T>(url: string, data?: unknown) => instance.put<never, T>(url, data),
    delete: <T>(url: string) => instance.delete<never, T>(url),
}

export default api
