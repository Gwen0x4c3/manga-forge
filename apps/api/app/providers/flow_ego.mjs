// Runs inside the official ego-browser Node runtime on the browser's computer.
// Only Flow UI operations run in the page. Files and MangaForge authentication stay in Node.
const fs = await import("node:fs/promises");
const path = await import("node:path");
const os = await import("node:os");
const { createHash, randomUUID } = await import("node:crypto");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const hash = (value) => createHash("sha256").update(value).digest("hex");
const flow = "https://flow.google.com/";
const uuid = /^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i;
const tileSelector = "flow-grid-tile-container";
const root = path.join(os.homedir(), ".mangaforge-flow", "ego", hash(request.endpoint));
const configFile = path.join(root, "pair.json");
const modelNames = {
    "veo-3.1-lite": "veo\\s*3\\.1\\s*[-–·]?\\s*lite",
    "omni-flash-1.2": "omni\\s*(?:flash\\s*1\\.2|1\\.2\\s*flash)",
    "nano-banana-2-lite": "nano banana 2 lite",
    "nano-banana-2": "nano banana 2(?:\\.1)?(?![.\\d]|\\s*lite)",
    "nano-banana-pro": "nano banana pro"
};

class FlowError extends Error {}
class TransportError extends Error {}
class Unauthorized extends Error {}
class ProfileMismatch extends Error {}
class AccountMismatch extends Error {}

async function readJson(file) {
    try {
        return JSON.parse(await fs.readFile(file, "utf8"));
    } catch (error) {
        if (error.code === "ENOENT") return null;
        throw error;
    }
}

async function saveJson(file, value) {
    const tmp = file + "." + randomUUID() + ".tmp";
    const handle = await fs.open(tmp, "wx", 0o600);
    try {
        await handle.writeFile(JSON.stringify(value));
        await handle.sync();
    } finally {
        await handle.close();
    }
    await fs.rename(tmp, file);
}

let settings;
async function api(route, { method = "POST", json = {}, bytes, binary = false } = {}) {
    const headers = { "X-Flow-Runner": request.runner };
    if (settings?.token) headers.Authorization = "Bearer " + settings.token;
    headers["Content-Type"] = bytes ? "application/octet-stream" : "application/json";
    let res;
    try {
        res = await fetch(request.endpoint + route, {
            method,
            headers,
            body: method === "GET" ? undefined : (bytes ?? JSON.stringify(json)),
            redirect: "error",
            signal: AbortSignal.timeout(60000)
        });
    } catch {
        throw new TransportError();
    }
    if (res.status === 401 || res.status === 403) throw new Unauthorized();
    if ([413, 422].includes(res.status))
        throw new FlowError("MangaForge 无法接收本次素材，请在 Flow 项目核对。");
    if (!res.ok) throw new TransportError();
    try {
        if (binary) return Buffer.from(await res.arrayBuffer());
        const body = await res.json();
        return body.data ?? body;
    } catch {
        throw new TransportError();
    }
}

function official(address) {
    const u = new URL(address);
    return (
        u.protocol === "https:" &&
        !u.username &&
        !u.password &&
        (["flow.google.com", "flow.google"].includes(u.host) ||
            (u.host === "labs.google" && /^\/fx\/(?:[\w-]+\/)?tools\/flow(?:\/|$)/.test(u.pathname)))
    );
}

function projectId(address) {
    if (!official(address)) return null;
    const id = new URL(address).pathname.replace(/\/$/, "").split("/project/")[1];
    return id && uuid.test(id) ? id : null;
}

// Inspect visible controls by their label. Use a concrete selector for the native SDK's real pointer events.
async function control(page, role, name, { scope, pattern = false } = {}) {
    return page.evaluate(
        ({ role, name, scope, pattern }) => {
            const aliases = {
                button: "button",
                textbox: "input:not([type]),input[type=text],textarea,[contenteditable=true]",
                radio: "input[type=radio]",
                slider: "input[type=range]"
            };
            const root = scope ? document.querySelector(scope) : document;
            if (!root) return null;
            const query = '[role="' + role + '"]' + (aliases[role] ? "," + aliases[role] : "");
            const matches = [];
            for (const el of root.querySelectorAll(query)) {
                if (!el.getClientRects().length || getComputedStyle(el).visibility === "hidden") continue;
                const clone = el.cloneNode(true);
                clone
                    .querySelectorAll("mat-icon,google-symbol,[aria-hidden=true],.material-symbols-outlined")
                    .forEach((x) => x.remove());
                const text = (clone.textContent || "").replace(/\s+/g, " ").trim();
                const labelled = (el.getAttribute("aria-labelledby") || "")
                    .split(/\s+/)
                    .map((id) => document.getElementById(id)?.textContent || "")
                    .join(" ")
                    .trim();
                const names = [el.getAttribute("aria-label"), labelled, text, el.getAttribute("title")].filter(
                    Boolean
                );
                if (!names.some((n) => (pattern ? new RegExp(name, "i").test(n) : n === name))) continue;
                const parts = [];
                for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
                    if (node.id) {
                        parts.unshift("#" + CSS.escape(node.id));
                        break;
                    }
                    let index = 1;
                    for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
                        if (sib.localName === node.localName) ++index;
                    }
                    parts.unshift(node.localName + ":nth-of-type(" + index + ")");
                }
                matches.push({
                    selector: parts.join(">"),
                    text,
                    checked: el.checked === true || el.getAttribute("aria-checked") === "true",
                    pressed: el.getAttribute("aria-pressed") === "true",
                    disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true"
                });
            }
            return matches.length === 1 ? matches[0] : null;
        },
        { role, name, scope, pattern }
    );
}

async function until(check, ms, message) {
    const end = Date.now() + ms;
    do {
        const result = await check();
        if (result) return result;
        await sleep(220);
    } while (Date.now() < end);
    throw new FlowError(message);
}

function required(page, role, name, options) {
    return until(
        () => control(page, role, name, options),
        6500,
        "未找到唯一的 Flow 控件，请查看 Ego 中的 Flow 页面。"
    );
}

async function click(page, role, name, options) {
    const item = await required(page, role, name, options);
    await page.click(item.selector);
}

async function signedIn(page) {
    if (!official(await page.url())) return false;
    return Boolean(
        (await control(page, "button", "Account details")) ||
        (await control(page, "button", "Settings trigger")) ||
        (await control(page, "button", "New project$", { pattern: true }))
    );
}

async function currentAccount(page) {
    if (!official(await page.url())) throw new AccountMismatch();
    // Only read the identifier displayed in Flow's own account panel; never inspect cookies or Google tokens.
    const identifier = () =>
        page.evaluate(() => {
            const panel = [...document.querySelectorAll('[role="dialog"],dialog[open]')].find(
                (d) =>
                    d.getClientRects().length &&
                    [...d.querySelectorAll("a")].some((a) => /switch account/i.test(a.innerText))
            );
            const addresses = panel?.innerText.match(/[\w.!#$%&'*+\/=?^_`{|}~-]+@[\w.-]+\.[a-z]{2,}/gi) || [];
            const distinct = [...new Set(addresses.map((s) => s.toLowerCase()))];
            return distinct.length === 1 ? distinct[0] : null;
        });
    let address = await identifier();
    if (!address) {
        const button = await control(page, "button", "Account details");
        if (!button) throw new AccountMismatch();
        await page.click(button.selector);
        address = await until(identifier, 5000, "").catch(() => null);
    }
    const close = await control(page, "button", "Close account panel");
    if (close) await page.click(close.selector);
    if (!address) throw new AccountMismatch();
    return hash(request.endpoint + "\n" + address);
}

async function verifyAccount(page, bind = false) {
    let digest;
    try {
        digest = await currentAccount(page);
    } catch {
        throw new AccountMismatch();
    }
    if (!settings.accountHash && bind) {
        settings.accountHash = digest;
        await saveJson(configFile, settings);
    }
    if (!settings.accountHash || settings.accountHash !== digest) throw new AccountMismatch();
}

async function openProject(page, id) {
    if (!uuid.test(id)) throw new FlowError("无效的 Flow 项目编号。");
    if (projectId(await page.url()) !== id) await page.goto(flow + "project/" + id + "?hl=en");
    await required(page, "button", "Settings trigger");
    if (projectId(await page.url()) !== id) throw new FlowError("当前账号无法打开该 Flow 项目。");
    await verifyAccount(page);
}

async function createProject(page, job, memo, save) {
    if (!memo.project) {
        if (memo.creating || (job.redelivered && !memo.received))
            throw new FlowError("新项目的创建结果待确认，请在 Flow 中核对。");
        await page.goto(flow + "?hl=en");
        await verifyAccount(page);
        const add = await required(page, "button", "New project$", { pattern: true });
        memo.creating = true;
        await save();
        await page.click(add.selector);
        memo.project = await until(async () => projectId(await page.url()), 30000, "Flow 尚未返回新项目编号。");
        await save();
    }
    await openProject(page, memo.project);
    const title = await required(page, "textbox", "Editable text");
    await page.fill(title.selector, job.title.slice(0, 110));
    await page.press(title.selector, "Enter");
    return { project: memo.project };
}

async function upload(page, job, prefix, dir, memo, save) {
    const raw = await api(prefix + "/inputs/0", { method: "GET", binary: true });
    if (hash(raw) !== job.digest) throw new FlowError("参考图摘要不匹配。");
    let ext;
    if (raw.subarray(0, 8).toString("hex") === "89504e470d0a1a0a") ext = "png";
    else if (raw.subarray(0, 3).toString("hex") === "ffd8ff") ext = "jpg";
    else if (raw.toString("ascii", 0, 4) === "RIFF" && raw.toString("ascii", 8, 12) === "WEBP") ext = "webp";
    else throw new FlowError("Flow 只接收 PNG、JPEG 和 WebP 参考图。");
    const name = "mf-" + job.digest + "." + ext;
    const selector = tileSelector + '[aria-label="' + name + '"] [data-media-id]';
    if (!(await page.evaluate((s) => Boolean(document.querySelector(s)), selector))) {
        if (memo.uploading) {
            await page.waitForSelector(selector, { state: "attached", timeout: 15000 });
            return { name };
        }
        const local = path.join(dir, name);
        await fs.writeFile(local, raw, { mode: 0o600 });
        await click(page, "button", "Add media menu");
        const item = await required(page, "menuitem", "Upload");
        const pending = page.waitForFileChooser({ timeout: 10000 });
        pending.catch(() => {});
        await page.click(item.selector);
        memo.uploading = true;
        await save();
        await (await pending).setFiles(local);
        await page.waitForSelector(selector, { state: "attached", timeout: 90000 });
    }
    return { name };
}

async function configure(page, job) {
    if (!Object.hasOwn(modelNames, job.model)) throw new FlowError("所选 Flow 模型未配置。");
    const agent = await control(page, "button", "^(Flow )?Agent$", { pattern: true });
    if (agent?.pressed) await page.click(agent.selector);
    const clear = await control(page, "button", "Clear prompt");
    if (clear) await page.click(clear.selector);
    await click(page, "button", "Settings trigger");
    async function select(name) {
        const option = await required(page, "radio", name);
        if (!option.checked) await page.click(option.selector);
    }
    await select(job.action === "video" ? "Video" : "Image");
    if (job.action === "video") await select("Ingredients");
    const model = await required(page, "button", "Select model family");
    if (!new RegExp(modelNames[job.model], "i").test(model.text)) {
        await page.click(model.selector);
        await click(page, "menuitem", modelNames[job.model], { pattern: true });
    }
    await select(job.ratio);
    if (job.action === "video") {
        const length = await control(page, "slider", "Length");
        if (length) {
            await page.press(length.selector, "Home");
            for (let i = 0; i < 5; i++) await page.press(length.selector, "ArrowRight");
            const eight = await page.evaluate(
                (s) =>
                    /Length\s*8\s*Sec/i.test(
                        document.querySelector(s)?.closest(".cdk-overlay-pane")?.innerText || ""
                    ),
                length.selector
            );
            if (!eight) throw new FlowError("Flow 时长未设为 8 秒，镜头尚未提交。");
        } else await select("8s");
    }
    await select("x1");
    await page.keyboard.press("Escape");
    if (await control(page, "button", "Select model family")) await click(page, "button", "Settings trigger");
}

async function attach(page, names) {
    for (const name of names) {
        if (!/^mf-[a-f0-9]{64}\.(png|jpg|webp)$/.test(name)) throw new FlowError("无效的参考图名称。");
        await click(page, "button", "Add ingredients to the prompt box");
        const tab = await control(page, "tab", "Uploads");
        if (tab) await page.click(tab.selector);
        const opt = { scope: "[role=listbox]", pattern: true },
            pattern = "^" + name.replace(".", "\\.");
        if (!(await control(page, "option", pattern, opt))) {
            const search = await control(page, "textbox", "search", { pattern: true });
            if (search) await page.fill(search.selector, name);
        }
        await click(page, "option", pattern, opt);
        const add = await control(page, "button", "Add to prompt");
        if (add) await page.click(add.selector);
        await page.waitForSelector("[role=listbox]", { state: "hidden", timeout: 10000 });
    }
    const count = await page.evaluate(
        () =>
            document.querySelectorAll('button[aria-label="Ingredient"],[role=button][aria-label="Ingredient"]')
                .length
    );
    if (count !== names.length) throw new FlowError("提示框的参考图数量与镜头方案不符，尚未提交。");
}

function inspectTiles(page) {
    return page.evaluate(
        (selector) => ({
            errors: document.querySelectorAll("flow-error-tile").length,
            tiles: [...document.querySelectorAll(selector)].map((t) => {
                const label = t.getAttribute("aria-label") || "";
                const kind = t.querySelector("flow-video-tile")
                    ? "video"
                    : t.querySelector("flow-image-tile")
                      ? "image"
                      : "";
                const id = t.querySelector("[data-media-id]")?.getAttribute("data-media-id") || label;
                const ready =
                    !label.startsWith("mf-") &&
                    !/\d+%/.test(t.innerText) &&
                    !!t.querySelector(
                        kind === "video" ? 'video,img[alt="Generated video thumbnail"]' : "img[src]"
                    );
                return { label, kind, id, ready };
            })
        }),
        tileSelector
    );
}

async function download(page, label, dest) {
    const tile = tileSelector + "[aria-label=" + JSON.stringify(label) + "]";
    await page.hover(tile);
    const more = await control(page, "button", "More options", { scope: tile });
    if (more) await page.click(more.selector);
    else await page.click(tile, { button: "right" });
    const menu = await required(page, "menuitem", "Download");
    const pending = page.waitForEvent("download", { timeout: 110000 });
    pending.catch(() => {});
    await page.click(menu.selector);
    const original = await until(
        () => control(page, "menuitem", "original", { pattern: true }),
        2000,
        ""
    ).catch(() => null);
    if (original) await page.click(original.selector);
    const part = dest + ".part";
    await (await pending).saveAs(part);
    await fs.rename(part, dest);
}

async function generate(page, job, memo, save, prefix, dest) {
    if (!memo.before) {
        if (job.redelivered && !memo.received && !memo.prepared)
            throw new FlowError("已领取的镜头缺少本地记录，请先在 Flow 核对。");
        await configure(page, job);
        await attach(page, job.references);
        const box = ".ProseMirror[contenteditable=true]";
        await page.click(box);
        await page.press(box, "ControlOrMeta+a");
        await page.keyboard.insertText(job.prompt.replace(/[\r\n]+/g, " ").trim());
        await verifyAccount(page);
        const start = await required(page, "button", "Start generation");
        if (start.disabled) throw new FlowError("Flow 生成按钮不可用，请检查素材和积分。");
        const view = await inspectTiles(page);
        if ((await api(prefix + "/heartbeat")).status !== "running") throw new FlowError("镜头任务已结束。");
        memo.before = view.tiles.map((t) => t.id);
        memo.errors = view.errors;
        memo.submitted = Date.now();
        await save(); // Always durable before the single credit-consuming action.
        await page.click(start.selector);
        return false;
    }
    if (!memo.tile) {
        const view = await inspectTiles(page);
        const fresh = view.tiles.filter(
            (t) => t.id && t.ready && t.kind === job.action && !memo.before.includes(t.id)
        );
        if (fresh.length > 1) throw new FlowError("同时出现多个新结果，请在 Flow 核对所属镜头。");
        if (!fresh.length) {
            if (view.errors > memo.errors) throw new FlowError("Google Flow 提示生成失败，请核对积分记录。");
            if (Date.now() - memo.submitted > 900000)
                throw new FlowError("镜头提交结果待核对，请打开对应 Flow 项目。");
            return false;
        }
        memo.tile = fresh[0].label;
        await save();
    }
    await download(page, memo.tile, dest);
    return true;
}

async function work(page, job) {
    if (!uuid.test(job.id)) throw new FlowError("无效的任务编号。");
    const prefix = "/jobs/" + job.id;
    const dir = path.join(root, "jobs", job.id),
        journal = path.join(dir, "journal.json"),
        dest = path.join(dir, "media");
    await fs.mkdir(dir, { recursive: true, mode: 0o700 });
    const memo = (await readJson(journal)) || {};
    const save = () => saveJson(journal, memo);
    if (!job.redelivered && !memo.received) {
        memo.received = true;
        await save();
    }
    if (!memo.reply) {
        try {
            if (!official(await page.url())) throw new FlowError("请在 Ego 标签页登录 Google Flow。");
            if (job.action === "project") memo.reply = await createProject(page, job, memo, save);
            else {
                await openProject(page, job.project);
                if (job.action === "upload") memo.reply = await upload(page, job, prefix, dir, memo, save);
                else if (["image", "video"].includes(job.action)) {
                    let size = (await fs.stat(dest).catch(() => null))?.size;
                    if (size === undefined) {
                        if (!(await generate(page, job, memo, save, prefix, dest))) return;
                        size = (await fs.stat(dest)).size;
                    }
                    if (size > 120 * 1024 * 1024 || !size) throw new FlowError("下载的媒体超过限制或为空。");
                    await api(prefix + "/media", { method: "PUT", bytes: await fs.readFile(dest) });
                } else throw new FlowError("未知的 Ego 浏览器任务。");
            }
        } catch (error) {
            if (
                error instanceof TransportError ||
                error instanceof Unauthorized ||
                error instanceof AccountMismatch
            )
                throw error;
            if (/EGO_.*(?:CONTROL|OWNERSHIP|INACTIVE|UNASSIGNED)/.test(String(error)))
                throw new TransportError();
            memo.reply = {
                error:
                    error instanceof FlowError ? error.message : "Ego 未能完成网页操作，请在专用标签页核对。",
                uncertain:
                    ["image", "video"].includes(job.action) &&
                    Boolean(memo.before || (job.redelivered && !memo.received && !memo.prepared))
            };
        }
        if (memo.reply) await save();
    }
    if (memo.reply) await api(prefix + "/finish", { json: memo.reply });
    await fs.rm(dir, { recursive: true, force: true });
}

async function browser(explicit) {
    const spaces = await listTaskSpaces();
    const entry = spaces.find((s) => s.id === settings.spaceId);
    if (entry && settings.profileId && entry.profileId !== settings.profileId) throw new ProfileMismatch();
    if (
        entry &&
        request.expectedProfile &&
        ![entry.profileName, entry.profileId].includes(request.expectedProfile)
    ) {
        throw new ProfileMismatch();
    }
    let task;
    if (!entry) {
        if (!explicit) return { state: "paused" };
        const provider = new URL(request.endpoint).pathname.split("/").pop().slice(0, 8);
        const name = "MangaForge Flow · " + provider + (settings.profileId ? " · " + settings.profileId : "");
        task = settings.profileId
            ? await taskSpace(name, { profileId: settings.profileId })
            : await taskSpace(name);
        const created = (await listTaskSpaces()).find((s) => s.id === task.spaceId);
        if (!created || (settings.profileId && created.profileId !== settings.profileId))
            throw new ProfileMismatch();
        settings.profileId = created.profileId;
        settings.spaceId = task.spaceId;
        settings.pageLabel = "p1";
        await saveJson(configFile, settings);
        await task.page("p1").goto(flow + "?hl=en");
    } else if (entry.ownership === "agent") task = await taskSpace(entry.id);
    else if (request.mode === "resume" && entry.ownership === "agentDelegatedToUser")
        task = await takeOverTaskSpace(entry.id);
    else if (request.mode === "resume" && entry.ownership === "user") {
        task = await claimTaskSpace(entry.id);
        const kept = (await task.tabs()).filter((tab) => official(tab.url));
        if (kept.length === 1) {
            const page = await task.adopt(kept[0].page);
            settings.pageLabel = page.label;
            await saveJson(configFile, settings);
        }
    } else return { state: "paused" };
    let page = (await task.pages()).find((p) => p.label === (settings.pageLabel || "p1"));
    if (!page) {
        if (!explicit) return { state: "paused" };
        page = await task.newPage();
        settings.pageLabel = page.label;
        await saveJson(configFile, settings);
        await page.goto(flow + "?hl=en");
    }
    if (
        (await signedIn(page)) ||
        (explicit &&
            official(await page.url()) &&
            (await until(() => signedIn(page), 5000, "").catch(() => false)))
    )
        return { state: "ready", page };
    await task.handOff();
    return { state: "login" };
}

async function main() {
    await fs.mkdir(root, { recursive: true, mode: 0o700 });
    settings = await readJson(configFile);
    if (request.mode === "pair") {
        let selected = settings?.profileId;
        if (request.profile) {
            const matches = (await profiles()).filter(
                (p) => p.id === request.profile || p.name === request.profile
            );
            if (matches.length !== 1) throw new ProfileMismatch();
            selected = matches[0].id;
        }
        const result = await api("/connect", { json: { code: request.code } });
        settings = {
            token: result.token,
            profileId: selected,
            spaceId: selected === settings?.profileId ? settings?.spaceId : undefined
        };
        await saveJson(configFile, settings);
    }
    if (!settings?.token) throw new Unauthorized();
    if (settings.accountPaused && request.mode === "tick") {
        await api("/presence", { json: { ready: false } });
        return "account_mismatch";
    }
    let connection;
    try {
        connection = await browser(["pair", "resume"].includes(request.mode));
    } catch (error) {
        if (error instanceof ProfileMismatch) await api("/presence", { json: { ready: false } });
        throw error;
    }
    const ready = connection.state === "ready";
    if (request.mode !== "tick") {
        if (ready) {
            await verifyAccount(connection.page, ["pair", "resume"].includes(request.mode));
            if (settings.accountPaused && request.mode === "resume") {
                delete settings.accountPaused;
                await saveJson(configFile, settings);
            }
        }
        // Probing never claims a job: the continuous connector will accept deliveries.
        await api("/presence", { json: { ready: ready && !settings.accountPaused } });
        return settings.accountPaused ? "account_mismatch" : connection.state;
    }
    const end = Date.now() + 18000;
    do {
        if (ready && !settings.accountHash) throw new AccountMismatch();
        const { job } = await api("/next", { json: { ready } });
        if (!ready) break;
        if (job) {
            const heart = setInterval(() => api("/jobs/" + job.id + "/heartbeat").catch(() => {}), 14000);
            try {
                await work(connection.page, job);
            } finally {
                clearInterval(heart);
            }
            break;
        }
        await sleep(2500);
    } while (Date.now() < end);
    return connection.state;
}

try {
    console.log("MF_FLOW " + JSON.stringify({ state: await main() }));
} catch (error) {
    if (error instanceof AccountMismatch && settings?.token) {
        settings.accountPaused = true;
        await saveJson(configFile, settings);
        await api("/presence", { json: { ready: false } }).catch(() => {});
    }
    const state =
        error instanceof Unauthorized
            ? "unauthorized"
            : error instanceof ProfileMismatch
              ? "profile_missing"
              : error instanceof AccountMismatch
                ? "account_mismatch"
                : "unavailable";
    console.log("MF_FLOW " + JSON.stringify({ state }));
}
