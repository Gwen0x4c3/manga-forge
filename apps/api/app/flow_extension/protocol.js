export const FLOW = "https://flow.google.com/";
export const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
export const MAX_MEDIA = 120 * 1024 * 1024;
export const CHUNK = 384 * 1024;

export function serverBase(value) {
    let u;
    try {
        u = new URL(value.trim());
    } catch {
        throw Error("请输入完整的 MangaForge 地址，包括 http 或 https。");
    }
    const local =
        /^(localhost|127(?:\.\d+){3}|10(?:\.\d+){3}|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|\[::1\]|\[f[cd][\da-f:]+\])$/i.test(
            u.hostname
        ) ||
        u.hostname.endsWith(".localhost") ||
        u.hostname.endsWith(".local");
    if (
        u.username ||
        u.password ||
        u.search ||
        u.hash ||
        !(u.protocol === "https:" || (u.protocol === "http:" && local))
    ) {
        throw Error("请使用 HTTPS，或填写本机、局域网 IP 的 HTTP 地址。");
    }
    const prefix = u.pathname.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
    return u.origin + prefix;
}

export function isFlow(address) {
    try {
        const u = new URL(address);
        return (
            u.protocol === "https:" &&
            !u.username &&
            !u.password &&
            (["flow.google.com", "flow.google"].includes(u.host) ||
                (u.host === "labs.google" && /^\/fx\/(?:[\w-]+\/)?tools\/flow(?:\/|$)/.test(u.pathname)))
        );
    } catch {
        return false;
    }
}

export function mediaHost(address) {
    try {
        const u = new URL(address);
        return (
            u.protocol === "https:" &&
            !u.username &&
            !u.password &&
            !u.port &&
            (u.hostname === "storage.googleapis.com" ||
                /(^|\.)(googleusercontent\.com|googlevideo\.com)$/.test(u.hostname))
        );
    } catch {
        return false;
    }
}

export function projectId(address) {
    if (!isFlow(address)) return null;
    const match = /\/project\/([^/]+)\/?$/.exec(new URL(address).pathname);
    return match && UUID.test(match[1]) ? match[1] : null;
}

export async function digest(bytes) {
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function encode(bytes) {
    let text = "";
    for (let start = 0; start < bytes.length; start += 24576) {
        text += btoa(String.fromCharCode(...bytes.subarray(start, start + 24576)));
    }
    return text;
}

export function decode(text) {
    return Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

export async function checkIssuer(server, token) {
    // Check the provider at the chosen URL before disclosing its bearer credential.
    const url = server + "/api/v1/flow/browsers/" + token.split(".")[1] + "/extension-token";
    try {
        const res = await fetch(url, {
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            cache: "no-store",
            signal: AbortSignal.timeout(10000)
        });
        const body = res.ok && (await res.json());
        if ((body?.data ?? body)?.issued === true) return;
    } catch {
        /* Return an actionable message without echoing credentials or response data. */
    }
    throw new ApiError("这个地址未确认该服务商的扩展令牌。请核对 MangaForge 地址和模型中心的令牌。", 0);
}

export async function api(cfg, path, { method = "POST", data, binary, file } = {}) {
    const headers = { Authorization: "Bearer " + cfg.token, "X-Flow-Runner": cfg.runner };
    if (method !== "GET") headers["Content-Type"] = file ? "application/octet-stream" : "application/json";
    let res;
    try {
        res = await fetch(cfg.server + "/api/v1/flow/" + path, {
            method,
            headers,
            body: method === "GET" ? undefined : (file ?? JSON.stringify(data ?? {})),
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            cache: "no-store",
            signal: AbortSignal.timeout(90000)
        });
    } catch {
        throw new ApiError("无法访问 MangaForge，请检查地址、网络和扩展的网站权限。", 0);
    }
    if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new ApiError(
            String(error.message || error.detail || "MangaForge HTTP " + res.status).slice(0, 200),
            res.status
        );
    }
    if (binary) return new Uint8Array(await res.arrayBuffer());
    const result = await res.json();
    return result.data ?? result;
}
