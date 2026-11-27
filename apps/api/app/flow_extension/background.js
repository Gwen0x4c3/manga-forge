import {
    api,
    ApiError,
    checkIssuer,
    CHUNK,
    decode,
    digest,
    encode,
    FLOW,
    isFlow,
    MAX_MEDIA,
    mediaHost,
    projectId,
    serverBase,
    UUID
} from "./protocol.js";

const local = chrome.storage.local;
const storageReady = local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" }).then(async () => {
    const { connection } = await local.get("connection");
    if (connection && Object.hasOwn(connection, "account")) {
        // Keep the installation, its token, pause preference and in-flight job records on upgrade.
        delete connection.account;
        await local.set({ connection });
        await status(connection.enabled ? "正在连接 Flow 标签页" : "已暂停，可点击「继续接收任务」", "idle");
    }
});
const ALARM = "mangaforge-flow";
const sites = chrome.runtime.getManifest().content_scripts[0].matches;
let pumping,
    timer,
    editing = false;
let lastJobAt = 0;

class TabIssue extends Error {
    constructor(message, kind = "page") {
        super(message);
        this.kind = kind;
    }
}
async function settings() {
    await storageReady;
    return (await local.get("connection")).connection;
}
const route = (cfg, path) => "browsers/" + cfg.provider + "/" + path;
const presence = (cfg, ready) => api(cfg, route(cfg, "presence"), { data: { ready } });
async function status(text, state) {
    await local.set({ status: { text, state, at: Date.now() } });
    await chrome.action.setBadgeText({ text: state === "working" ? "▶" : state === "attention" ? "!" : "" });
    await chrome.action.setBadgeBackgroundColor({ color: state === "attention" ? "#ae5c21" : "#17685d" });
}
async function activeFlowTab() {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (isFlow(tab?.url)) return tab;
}
async function rememberActiveTab() {
    const tab = await activeFlowTab();
    if (tab) await chrome.storage.session.set({ flowTab: tab.id });
}
async function findTab() {
    const active = await activeFlowTab();
    if (active) return active;
    const { flowTab } = await chrome.storage.session.get("flowTab");
    if (flowTab) {
        const tab = await chrome.tabs.get(flowTab).catch(() => null);
        if (isFlow(tab?.url)) return tab;
    }
    const tabs = (await chrome.tabs.query({ url: sites })).filter((t) => isFlow(t.url));
    return tabs.length === 1 ? tabs[0] : undefined;
}
async function rpc(tab, op, args = {}) {
    const message = { channel: "mf-flow-" + chrome.runtime.getManifest().version, op, ...args };
    let response;
    let missingReceiver = false;
    try {
        response = await chrome.tabs.sendMessage(tab, message, { frameId: 0 });
    } catch (error) {
        if (!String(error.message).includes("Receiving end does not exist"))
            throw new TabIssue("Flow 标签页正在切换。", "offline");
        missingReceiver = true;
    }
    if (missingReceiver || (!response && op === "probe")) {
        const target = await chrome.tabs.get(tab).catch(() => null);
        if (!isFlow(target?.url)) throw new TabIssue("请打开要使用的 Google Flow 标签页。", "offline");
        // A tab may predate the installation or still have the old script. Probing is read-only.
        try {
            await chrome.scripting.executeScript({ target: { tabId: tab }, files: ["flow.js"] });
            response = await chrome.tabs.sendMessage(tab, message, { frameId: 0 });
        } catch {
            throw new TabIssue("暂时无法连接 Flow 标签页。", "offline");
        }
    }
    if (!response) throw new TabIssue("Flow 标签页已关闭或刷新。", "offline");
    if (!response.ok) throw new TabIssue(response.error, response.kind);
    return response.value;
}
async function ownedConfig(cfg) {
    const current = await settings();
    if (editing || !current || current.session !== cfg.session || !current.enabled)
        throw new TabIssue("扩展已暂停或已更换连接。", "offline");
}
function later(ms) {
    clearTimeout(timer);
    timer = setTimeout(kick, ms);
}
function officialPage(tab, project) {
    // Navigate within the user's chosen Flow site, retaining the tab's existing query and route prefix.
    const u = new URL(tab.url);
    const root = u.hostname === "labs.google"
        ? u.pathname.match(/^\/fx\/(?:[\w-]+\/)?tools\/flow/)[0]
        : (u.pathname.match(/^\/u\/\d+(?=\/|$)/)?.[0] || "");
    u.pathname = root + (project ? "/project/" + project : "/");
    u.hash = "";
    u.searchParams.set("hl", "en");
    return u.href;
}
async function mediaFile(tab, job, memo) {
    const handle = crypto.randomUUID();
    const result = await rpc(tab, "result", { id: memo.tile, kind: job.action, handle });
    if (result.url) {
        if (!mediaHost(result.url)) throw new TabIssue("无法读取 Flow 结果，请在原项目核对媒体。");
        const res = await fetch(result.url, {
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            signal: AbortSignal.timeout(60000)
        });
        if (!res.ok || Number(res.headers.get("content-length")) > MAX_MEDIA)
            throw new TabIssue("Google 未返回可用的媒体文件。");
        const blob = await res.blob();
        if (!blob.size || blob.size > MAX_MEDIA) throw new TabIssue("Flow 媒体大小无效。");
        return blob;
    }
    if (!Number.isSafeInteger(result.size) || result.size <= 0 || result.size > MAX_MEDIA)
        throw new TabIssue("媒体长度无效。");
    const parts = [];
    try {
        for (let offset = 0; offset < result.size; offset += CHUNK) {
            const chunk = decode(await rpc(tab, "chunk", { handle, offset }));
            if (chunk.length !== Math.min(CHUNK, result.size - offset))
                throw new TabIssue("媒体传输中断。", "offline");
            parts.push(chunk);
        }
        return new Blob(parts);
    } finally {
        await rpc(tab, "release", { handle }).catch(() => {});
    }
}
async function jobStep(cfg, tab, job, memo, save) {
    const base = route(cfg, "jobs/" + job.id);
    const page = (op, args) => rpc(tab.id, op, args);
    const project = projectId(tab.url);
    if (memo.reply) return memo.reply;
    if (job.action === "project") {
        if (!memo.creating) {
            if (!memo.received) throw new TabIssue("找不到已领取项目的本地记录，请核对 Flow 项目。");
            if (new URL(tab.url).pathname.replace(/\/$/, "") !== new URL(officialPage(tab)).pathname.replace(/\/$/, "")) {
                await chrome.tabs.update(tab.id, { url: officialPage(tab) });
                return;
            }
            memo.creating = Date.now();
            await save();
            await page("new");
            return;
        }
        if (!project) {
            if (Date.now() - memo.creating > 40000) throw new TabIssue("Flow 没有返回新项目，请核对项目列表。");
            return;
        }
        await page("rename", { title: job.title });
        return { project, project_url: new URL(tab.url).origin + new URL(tab.url).pathname };
    }
    if (!UUID.test(job.project)) throw new TabIssue("MangaForge 项目编号无效。");
    if (project !== job.project) {
        if (memo.navigation && Date.now() - memo.navigation < 5000) return;
        if ((memo.navigations || 0) >= 3) throw new TabIssue("Flow 标签页无法打开这个项目。");
        memo.navigation = Date.now();
        memo.navigations = (memo.navigations || 0) + 1;
        await save();
        await chrome.tabs.update(tab.id, { url: officialPage(tab, job.project) });
        return;
    }
    if (job.action === "upload") {
        const readFile = async () => {
            const raw = await api(cfg, base + "/inputs/0", { method: "GET", binary: true });
            if (raw.length > 20_000_000 || (await digest(raw)) !== job.digest)
                throw new TabIssue("参考图大小或摘要不符。");
            return raw;
        };
        let raw;
        if (!memo.name) {
            raw = await readFile();
            const ext = raw[0] === 137 ? "png" : raw[0] === 255 ? "jpg" : "webp";
            memo.name = "mf-" + job.digest + "." + ext;
        }
        // A resumed upload has the same job ID and a new local attempt, so a previous Cancel is not replayed.
        memo.attempt ??= crypto.randomUUID();
        const ref = { name: memo.name, attempt: memo.attempt };
        const url = new URL(tab.url);
        const projectUrl = url.origin + url.pathname;
        const { state, progress, documentId } = await page("uploadState", ref);
        if (state === "uploaded") return { name: memo.name, project_url: projectUrl };
        if (state === "cancelled") throw new TabIssue("已取消 Flow 的素材使用权确认，同步已停止。");
        const waiting = state === "rights";
        if (waiting !== Boolean(memo.waiting)) {
            await api(cfg, base + "/heartbeat", { data: {
                waiting_for: waiting ? "upload_rights" : null, project_url: projectUrl
            } });
            memo.waiting = waiting;
            if (!waiting) {
                if (memo.uploading) memo.uploading = Date.now();
                else memo.afterConsent = Date.now(); // A file selected before this attempt may still appear.
            }
            await save();
        }
        if (waiting) {
            await status("请在当前 Flow 标签页确认素材使用权，确认后将自动继续", "attention");
            return;
        }
        if (state === "transferring") {
            if (!memo.uploading || memo.progress !== progress || memo.uploadPage !== documentId) {
                memo.uploadPage = documentId;
                memo.progress = progress;
                memo.uploading = Date.now();
                await save();
            }
            if (Date.now() - memo.uploading > 180000) throw new TabIssue("Flow 上传进度已停滞，请检查网络后继续同步。");
            return;
        }
        if (memo.afterConsent && Date.now() - memo.afterConsent < 4500) return;
        // A refresh discards pending File objects. Check the gallery before sending the same digest again.
        if (memo.uploadPage && memo.uploadPage !== documentId) delete memo.uploading;
        if (memo.uploading) {
            if (Date.now() - memo.uploading > 90000) throw new TabIssue("Flow 未显示这张参考图，请查看原项目后继续同步。");
            return;
        }
        raw ??= await readFile();
        memo.uploading = Date.now();
        memo.uploadPage = documentId;
        await save();
        if (!(await page("upload", { ...ref, bytes: encode(raw) }))) {
            delete memo.uploading; // The dialog opened before Flow received the file.
            await save();
        }
        return;
    }
    if (!["image", "video"].includes(job.action)) throw new TabIssue("未知的媒体任务。");
    if (!memo.sent) {
        if (!memo.received) throw new TabIssue("这个镜头的提交记录不在当前扩展，请在 Flow 核对。");
        let view;
        try {
            view = await page("prepare", { job });
        } catch (error) {
            if (error.kind !== "missing_reference" || memo.refreshedAssets) throw error;
            // A long-lived Flow tab can have an older asset list than the tab which performed the uploads.
            memo.refreshedAssets = true;
            await save();
            await chrome.tabs.reload(tab.id);
            return;
        }
        await ownedConfig(cfg);
        if ((await api(cfg, base + "/heartbeat")).status !== "running") throw new TabIssue("镜头任务已结束。");
        memo.before = view.tiles.map((t) => t.id);
        memo.errors = view.errors;
        memo.sent = Date.now();
        await save(); // Chrome may suspend the worker before it receives the button's reply.
        try {
            await page("submit", { prompt: job.prompt, referenceCount: job.references.length });
        } catch (error) {
            if (error.kind === "unsubmitted") {
                delete memo.sent;
                delete memo.before;
                delete memo.errors;
                await save();
            }
            throw error;
        }
        return;
    }
    if (!memo.tile) {
        const view = await page("inventory");
        const fresh = view.tiles.filter(
            (t) => t.id && t.kind === job.action && t.ready && !memo.before.includes(t.id)
        );
        if (fresh.length > 1) throw new TabIssue("同时出现了多个 Flow 结果，请在项目里核对本次镜头。");
        if (!fresh.length) {
            if (view.errors > memo.errors) throw new TabIssue("Flow 报告生成失败，请在项目核对。");
            if (Date.now() - memo.sent > 900000) throw new TabIssue("Flow 尚未返回结果，请在原项目核对。");
            return;
        }
        memo.tile = fresh[0].id;
        await save();
    }
    const file = await mediaFile(tab.id, job, memo);
    await api(cfg, base + "/media", { method: "PUT", file });
    return { media: true };
}
async function work(cfg, tab, job) {
    if (!UUID.test(job.id)) throw new TabIssue("无效的任务编号。");
    const key = "job:" + cfg.session + ":" + job.id;
    const previous = (await local.get(key))[key];
    const memo = previous ?? { received: !job.redelivered };
    const save = () => local.set({ [key]: memo });
    await save();
    const base = route(cfg, "jobs/" + job.id);
    const heart = setInterval(() => api(cfg, base + "/heartbeat").catch(() => {}), 14000);
    try {
        let reply;
        try {
            // Keep each browser action on its starting tab while the user moves between tabs.
            const { jobTarget } = await chrome.storage.session.get("jobTarget");
            if (jobTarget?.id === job.id && jobTarget.tab !== tab.id) {
                const original = await chrome.tabs.get(jobTarget.tab).catch(() => null);
                if (isFlow(original?.url)) tab = original;
                else if (memo.creating && !memo.reply)
                    throw new TabIssue("创建项目时使用的标签页已关闭，请先查看 Flow 项目列表。");
            }
            if (jobTarget?.id !== job.id || jobTarget.tab !== tab.id) {
                await chrome.storage.session.set({ jobTarget: { id: job.id, tab: tab.id } });
            }
            if (!memo.waiting) await status({
                project: "正在创建 Flow 项目", upload: "正在同步参考图", image: "正在生成图片", video: "正在生成镜头"
            }[job.action] || "正在处理任务", "working");
            reply = await jobStep(cfg, tab, job, memo, save);
        } catch (err) {
            if (
                (err instanceof ApiError && ![413, 422].includes(err.status)) ||
                err.kind === "offline"
            )
                throw err;
            reply = {
                error:
                    err instanceof TabIssue || err instanceof ApiError
                        ? err.message
                        : "读取 Flow 媒体失败，请在原项目核对。",
                uncertain: ["video", "image"].includes(job.action) && Boolean(memo.sent || !memo.received)
            };
        }
        if (!reply) return memo.waiting ? 4500 : 1800;
        if (!reply.media) {
            memo.reply = reply;
            await save();
            await api(cfg, base + "/finish", { data: reply });
        }
        await local.remove(key);
        await chrome.storage.session.remove("jobTarget");
        if (reply.error) await status(reply.error, "attention");
    } finally {
        clearInterval(heart);
    }
}
async function pump() {
    const cfg = await settings();
    if (!cfg?.enabled || editing) return;
    try {
        const tab = await findTab();
        if (!tab || !(await rpc(tab.id, "probe")))
            throw new TabIssue("请打开或选中要使用的 Google Flow 标签页。", "offline");
        const { job } = await api(cfg, route(cfg, "next"), { data: { ready: true } });
        if (job) {
            lastJobAt = Date.now();
            later((await work(cfg, tab, job)) || 1800);
        } else {
            await status("已连接，等待 MangaForge 任务", "ready");
            if (Date.now() - lastJobAt < 15000) later(3000);
        }
    } catch (error) {
        if (error instanceof TabIssue) await presence(cfg, false).catch(() => {});
        if (error instanceof ApiError && error.status === 403) {
            await local.set({ connection: { ...cfg, enabled: false } });
        }
        await status(
            error instanceof ApiError || error instanceof TabIssue
                ? error.message
                : "连接暂时中断，稍后自动重试。",
            "attention"
        );
    }
}
function kick() {
    if (!pumping && !editing)
        pumping = pump().finally(() => {
            pumping = null;
        });
    return pumping;
}
async function ensureAlarm() {
    if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
}
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === ALARM) kick();
});
chrome.runtime.onStartup.addListener(() => {
    ensureAlarm();
    kick();
});
chrome.runtime.onInstalled.addListener(() => {
    ensureAlarm();
    kick();
});
chrome.tabs.onActivated.addListener(() => { rememberActiveTab().catch(() => {}); });
chrome.windows.onFocusChanged.addListener(() => { rememberActiveTab().catch(() => {}); });
chrome.tabs.onUpdated.addListener((id, change, tab) => {
    if (change.status === "complete" && isFlow(tab.url)) {
        if (tab.active) rememberActiveTab().catch(() => {});
        later(800);
    }
});
ensureAlarm().catch(() => {});

async function popup(m) {
    const cfg = await settings();
    if (m.op === "view") {
        const { status: notice } = await local.get("status");
        return {
            server: cfg?.server,
            provider: cfg?.name,
            enabled: cfg?.enabled,
            status: notice
        };
    }
    if (m.op === "open") {
        const tab = await findTab();
        if (tab) {
            await chrome.windows.update(tab.windowId, { focused: true });
            await chrome.tabs.update(tab.id, { active: true });
        } else await chrome.tabs.create({ url: FLOW + "?hl=en" });
        return;
    }
    if (editing) throw Error("正在更新连接。");
    editing = true;
    try {
        if (pumping) await pumping;
        if (m.op === "pause" || m.op === "forget") {
            if (!cfg) return;
            await local.set({ connection: { ...cfg, enabled: false } });
            await presence(cfg, false).catch(() => {});
            if (m.op === "forget") {
                await local.remove("connection");
                await chrome.storage.session.remove("flowTab");
            }
            await status(m.op === "pause" ? "已暂停接收任务" : "已移除本机令牌", "idle");
            return;
        }
        if (m.op !== "connect" && m.op !== "resume") throw Error("未知操作。");
        const server = m.op === "resume" ? cfg.server : serverBase(m.server);
        const token = m.op === "resume" ? cfg.token : (m.token || "").trim();
        if (!/^mf_flow\.[\da-f-]{36}\.[\w-]{43}$/.test(token))
            throw Error("请粘贴模型中心签发的 MangaForge 扩展令牌。");
        if (m.op === "connect") await checkIssuer(server, token);
        let { installation: runner } = await local.get("installation");
        if (!runner) {
            runner = crypto.randomUUID();
            await local.set({ installation: runner });
        }
        const candidate = { server, token, runner };
        const info = await api(candidate, "extension/connect");
        if (!UUID.test(info.provider_id) || !UUID.test(info.session)) throw Error("MangaForge 返回了无效的连接。");
        if (cfg && (cfg.session !== info.session || cfg.server !== server))
            await presence(cfg, false).catch(() => {});
        await local.set({
            connection: {
                ...candidate,
                provider: info.provider_id,
                name: info.name,
                session: info.session,
                enabled: true
            }
        });
        await status("已连接 MangaForge，正在查找 Flow 标签页", "ready");
        later(100);
    } finally {
        editing = false;
    }
}
chrome.runtime.onMessage.addListener((m, sender, reply) => {
    if (
        sender.id !== chrome.runtime.id ||
        sender.url !== chrome.runtime.getURL("popup.html") ||
        m?.channel !== "mf-settings"
    )
        return;
    popup(m)
        .then((value) => reply({ ok: true, value }))
        .catch((e) => reply({ ok: false, error: e.message }));
    return true;
});
