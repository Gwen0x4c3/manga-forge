import { isFlow, serverBase } from "./protocol.js";
const $ = (id) => document.getElementById(id);
let current;
const call = async (op, args = {}) => {
    const r = await chrome.runtime.sendMessage({ channel: "mf-settings", op, ...args });
    if (!r?.ok) throw Error(r?.error || "无法连接扩展后台。");
    return r.value;
};
function notice(text, error = false) {
    $("notice").textContent = text;
    $("notice").dataset.error = String(error);
}
async function show() {
    current = await call("view");
    if (!(await chrome.tabs.getCurrent())) {
        const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
        if (isFlow(active?.url)) await chrome.storage.session.set({ flowTab: active.id });
        if (!current.provider) {
            // Keep first-time setup alive while Chrome displays its native host permission prompt.
            await chrome.runtime.openOptionsPage();
            window.close();
            return;
        }
    }
    $("setup").hidden = !!current.provider;
    $("connected").hidden = !current.provider;
    if (current.provider) {
        $("bound-server").textContent = current.server;
        $("provider").textContent = current.provider;
        $("toggle").textContent = current.enabled ? "暂停接收任务" : "继续接收任务";
        notice(current.status?.text || "正在检查连接", current.status?.state === "attention");
    } else {
        $("connect").disabled = false;
        if (!$("server").value)
            $("server").value = chrome.runtime.getManifest().homepage_url?.replace(/\/$/, "") || "";
        notice("填入模型中心的扩展令牌。任务会在你选好的 Flow 标签页中运行。");
    }
}
$("setup").onsubmit = async (e) => {
    e.preventDefault();
    $("connect").disabled = true;
    try {
        const server = serverBase($("server").value),
            url = new URL(server);
        // Request only the chosen host, directly from this user gesture.
        const granted = await chrome.permissions.request({ origins: [url.protocol + "//" + url.hostname + "/*"] });
        if (!granted) throw Error("需要允许扩展访问你填写的 MangaForge 主机。");
        notice("正在连接…");
        await call("connect", { server, token: $("token").value });
        $("token").value = "";
        await show();
    } catch (err) {
        notice(err.message, true);
        $("connect").disabled = false;
    }
};
$("toggle").onclick = async () => {
    $("toggle").disabled = true;
    try {
        await call(current.enabled ? "pause" : "resume");
        await show();
    } catch (e) {
        notice(e.message, true);
    } finally {
        $("toggle").disabled = false;
    }
};
$("forget").onclick = async () => {
    try {
        await call("forget");
        const u = new URL(current.server);
        await chrome.permissions.remove({ origins: [u.protocol + "//" + u.hostname + "/*"] });
        await show();
    } catch (e) {
        notice(e.message, true);
    }
};
$("open").onclick = () => call("open").catch((e) => notice(e.message, true));
chrome.storage.onChanged.addListener((change, area) => {
    if (area === "local" && current?.provider && change.status?.newValue) {
        const s = change.status.newValue;
        notice(s.text, s.state === "attention");
    }
    if (area === "local" && current?.provider && change.connection?.newValue) {
        current.enabled = change.connection.newValue.enabled;
        $("toggle").textContent = current.enabled ? "暂停接收任务" : "继续接收任务";
    }
});
show().catch((e) => notice(e.message, true));
