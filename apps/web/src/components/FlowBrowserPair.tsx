import { useState } from 'react'
import { Button, Input, Popconfirm } from '@douyinfe/semi-ui'
import { useMutation, useQuery } from '@tanstack/react-query'
import api from '@/services/api'

export const browserStatus = (status?: string | null) => ({
    ready: 'Flow 网页已连接', offline: '浏览器离线', login_required: '等待 Flow 标签页就绪', unpaired: '等待扩展连接',
})[status || 'unpaired']

export default function FlowBrowserPair({ providerId, status }: { providerId?: string; status?: string | null }) {
    const [copied, setCopied] = useState(false)
    const [token, setToken] = useState('')
    const [tokenCopied, setTokenCopied] = useState(false)
    const tokenUrl = `/flow/browsers/${providerId}/extension-token`
    const manage = { headers: { 'X-MangaForge-Manage': 'flow-extension' } }
    const access = useQuery({
        queryKey: ['flow-extension-access', providerId], enabled: !!providerId,
        queryFn: () => api.get<{ issued: boolean }>(tokenUrl),
    })
    const issue = useMutation({
        gcTime: 0, mutationFn: () => api.post<{ token: string }>(tokenUrl, {}, manage),
        onSuccess: data => { setToken(data.token); setTokenCopied(false); access.refetch() },
    })
    const revoke = useMutation({
        mutationFn: () => api.delete(tokenUrl, manage),
        onSuccess: () => { setToken(''); access.refetch() },
    })
    const [browser, setBrowser] = useState<'ego' | 'chrome'>('ego')
    const pairing = useMutation({
        mutationFn: () => api.post<{ code: string }>(`/flow/browsers/${providerId}/pair`),
        onSuccess: () => setCopied(false),
    })
    const link = pairing.data && `${window.location.origin}/api/v1/flow/browsers/${providerId}#${pairing.data.code}`
    return (
        <div className="space-y-2 rounded border border-[var(--border)] p-3 text-sm">
            <strong>Chrome 扩展{providerId && ` · ${browserStatus(status)}`}</strong>
            <p><a className="text-[var(--accent)]" href={'/api/v1/flow/extension.zip?server=' + encodeURIComponent(window.location.origin)} download>下载 MangaForge Flow 扩展（ZIP）</a>。
                解压后，在目标浏览器的 <code>chrome://extensions</code> 开启开发者模式，选择「加载已解压的扩展程序」。</p>
            <p>在扩展中填写 MangaForge 地址 <code>{window.location.origin}</code> 和此服务商的令牌。Google 账号由你在 Flow 标签页中选择。</p>
            <p>升级已安装的扩展时，用 ZIP 里的文件覆盖原目录，再到 <code>chrome://extensions</code> 点击「重新加载」。</p>
            {providerId ? <div className="flex flex-wrap gap-2">
                {access.data?.issued ? <>
                    <Popconfirm title="更换扩展令牌？" content="现有扩展需要重新填写新令牌。" onConfirm={() => issue.mutate()}>
                        <Button size="small" loading={issue.isPending}>更换扩展令牌</Button>
                    </Popconfirm>
                    <Popconfirm title="撤销扩展令牌？" content="此令牌的浏览器将失去任务访问权限。" onConfirm={() => revoke.mutate()}>
                        <Button size="small" loading={revoke.isPending}>撤销令牌</Button>
                    </Popconfirm>
                </> : <Button size="small" disabled={!access.data} loading={issue.isPending} onClick={() => issue.mutate()}>生成扩展令牌</Button>}
            </div> : <p>保存服务商后即可生成扩展令牌。</p>}
            {token && <div className="space-y-2">
                <label htmlFor="flow-extension-token">扩展令牌（仅本次显示）</label>
                <Input id="flow-extension-token" readOnly value={token} onFocus={e => e.target.select()} />
                <Button size="small" onClick={async () => {
                    const field = document.querySelector<HTMLInputElement>('#flow-extension-token')
                    try { await navigator.clipboard.writeText(token); setTokenCopied(true) }
                    catch { field?.focus(); field?.select(); setTokenCopied(document.execCommand('copy')) }
                }}>{tokenCopied ? '已复制' : '复制令牌'}</Button>
            </div>}
            <details><summary className="cursor-pointer text-[var(--text-muted)]">其他连接方式</summary>
            <div role="group" aria-label="连接方式" className="flex gap-4">
                <label><input type="radio" name="flow-browser" checked={browser === 'ego'}
                    onChange={() => setBrowser('ego')} /> Ego Lite</label>
                <label><input type="radio" name="flow-browser" checked={browser === 'chrome'}
                    onChange={() => setBrowser('chrome')} /> 专用 Chrome</label>
            </div>
            {browser === 'ego' ? <>
                <p>在已连接 Mac Ego Bridge 的 Linux 主机上，进入 MangaForge 项目目录运行下面的命令，按提示粘贴本页配对串。Mac 上使用 Ego Lite 已登录的 Google 账号。</p>
                <pre className="overflow-auto select-all">make flow-ego</pre>
                <p>如有多个 Ego profile，先在目标 profile 的 Flow 账号菜单选好 Google 账号，再运行 <code>python3 scripts/flow_ego.py --profile '完整名称'</code>。生成前会核对已绑定的账号。</p>
                <p>制作期间保持 Mac 唤醒、Ego Lite 和连接器在线。如果 Flow 要求登录，在专用标签页登录后运行 <code>make flow-ego-resume</code>。</p>
            </> : <>
                <p>在装有 Chrome 和 Python 3.10+ 的电脑下载连接器，在下载目录运行下面两行。按提示配对并在专用 Chrome 窗口登录 Ultra 账号。</p>
                <a className="text-[var(--accent)]" href="/api/v1/flow/connector" download>下载本地连接器（Python）</a>
                <pre className="overflow-auto select-all">{'python -m pip install playwright\npython mangaforge_flow.py'}</pre>
            </>}
            {providerId ? <Button size="small" loading={pairing.isPending} onClick={() => pairing.mutate()}>
                {status && status !== 'unpaired' ? '生成重新配对串' : '生成一次性配对串'}
            </Button> : <p>保存服务商后即可生成配对串。Google 登录信息保留在你的浏览器。</p>}
            {link && <div className="space-y-2">
                <label htmlFor="flow-pair-link">将配对串粘贴到本地连接器，10 分钟内有效</label>
                <Input id="flow-pair-link" readOnly value={link} onFocus={e => e.target.select()} />
                {navigator.clipboard && <Button size="small" onClick={async () => {
                    try { await navigator.clipboard.writeText(link); setCopied(true) }
                    catch { document.querySelector<HTMLInputElement>('#flow-pair-link')?.select() }
                }}>{copied ? '已复制' : '复制配对串'}</Button>}
            </div>}
            </details>
        </div>
    )
}
