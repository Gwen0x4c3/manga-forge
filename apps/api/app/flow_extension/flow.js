// Isolated content script. It operates the Flow page and never receives a MangaForge credential.
(() => {
    const channel = "mf-flow-" + chrome.runtime.getManifest().version;
    if (globalThis.__mangaForgeFlowLoaded === channel) return;
    globalThis.__mangaForgeFlowLoaded = channel;
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const tileTag = "flow-grid-tile-container";
    const referenceName = /^mf-[a-f0-9]{64}\.(png|jpg|webp)$/;
    const models = {
        "veo-3.1-lite": /veo\s*3\.1\s*[-–·]?\s*lite/i,
        "omni-flash-1.2": /omni\s*(?:flash\s*1\.2|1\.2\s*flash)/i,
        "nano-banana-2-lite": /nano banana 2 lite/i,
        "nano-banana-2": /nano banana 2(?:\.1)?(?![.\d]|\s*lite)/i,
        "nano-banana-pro": /nano banana pro/i
    };
    const synonyms = {
        "Settings trigger": ["设置", "設定"],
        "Editable text": ["可编辑文本"],
        "Add media menu": ["添加媒体菜单"],
        Upload: ["上传", "上傳"],
        Video: ["视频", "影片"],
        Image: ["图片", "图像", "圖片"],
        Ingredients: ["素材"],
        Length: ["时长", "長度"],
        Uploads: ["上传内容", "已上传"],
        "Clear prompt": ["清除提示"],
        "Add to prompt": ["添加到提示"],
        "Start generation": ["开始生成", "生成"]
    };
    const visible = (el) => el && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden";
    const roles = {
        button: "button",
        textbox: "input:not([type]),input[type=text],textarea,[contenteditable=true]",
        radio: "input[type=radio]",
        slider: "input[type=range]"
    };
    let retained;
    class PageError extends Error {
        constructor(message, kind = "page") {
            super(message);
            this.kind = kind;
        }
    }
    async function waitFor(check, message, ms = 7000, kind = "page") {
        const until = Date.now() + ms;
        do {
            const result = check();
            if (result) return result;
            await sleep(150);
        } while (Date.now() < until);
        throw new PageError(message, kind);
    }
    function matchingControls(role, label, root = document) {
        const selector = '[role="' + role + '"]' + (roles[role] ? "," + roles[role] : "");
        return [...root.querySelectorAll(selector)].filter((el) => {
            if (!visible(el)) return false;
            const copy = el.cloneNode(true);
            copy.querySelectorAll("mat-icon,google-symbol,[aria-hidden=true],.material-symbols-outlined").forEach(
                (n) => n.remove()
            );
            const labels = [
                el.getAttribute("aria-label"),
                el.title,
                copy.textContent,
                (el.getAttribute("aria-labelledby") || "")
                    .split(/\s+/)
                    .map((id) => document.getElementById(id)?.textContent)
                    .join(" ")
            ];
            return labels.some((value) => {
                const text = (value || "").trim().replace(/\s+/g, " ");
                return label instanceof RegExp
                    ? label.test(text)
                    : text === label || synonyms[label]?.includes(text);
            });
        });
    }
    function control(role, label, root) {
        const matches = matchingControls(role, label, root);
        return matches.length === 1 ? matches[0] : null;
    }
    const need = (role, label, root) =>
        waitFor(() => control(role, label, root), "Flow 页面找不到唯一的控件 " + label);
    async function click(role, label, root) {
        (await need(role, label, root)).click();
    }
    function key(el, name) {
        el.focus();
        for (const type of ["keydown", "keyup"])
            el.dispatchEvent(new KeyboardEvent(type, { key: name, bubbles: true, cancelable: true }));
    }
    function fill(el, value) {
        el.focus();
        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
            const proto =
                el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
            Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
            const range = document.createRange();
            range.selectNodeContents(el);
            const selection = getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            if (!document.execCommand("insertText", false, value)) {
                el.textContent = value;
                el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
            }
        }
    }
    function tiles() {
        return [...document.querySelectorAll(tileTag)].map((el) => {
            const label = el.getAttribute("aria-label") || "";
            const id = el.querySelector("[data-media-id]")?.getAttribute("data-media-id") || label;
            const kind = el.querySelector("flow-video-tile")
                ? "video"
                : el.querySelector("flow-image-tile")
                  ? "image"
                  : "";
            const ready =
                kind &&
                !label.startsWith("mf-") &&
                !/\d+%/.test(el.innerText) &&
                Boolean(el.querySelector(kind === "video" ? 'video,img[alt*="video" i]' : "img[src],img[srcset]"));
            return { el, label, id, kind, ready: Boolean(ready) };
        });
    }
    const inventory = () => ({
        tiles: tiles().map(({ id, kind, ready }) => ({ id, kind, ready })),
        errors: document.querySelectorAll("flow-error-tile").length
    });
    const rightsTitle = /^(?:Rights to use this image|(?:使用(?:此|这张|這張)?(?:图片|图像|圖片|圖像)的(?:权利|權利)|(?:图片|图像|圖片|圖像)(?:的)?使用[权權]))$/i;
    function rightsDialog() {
        return [...document.querySelectorAll('[role="dialog"],mat-dialog-container,dialog[open]')].find(el =>
            visible(el) && [el.getAttribute("aria-label"), el.querySelector("h1,h2,h3,[role=heading]")?.textContent]
                .some(title => title && rightsTitle.test(title.trim()))
        );
    }
    let trackedUpload;
    function uploadState(name, attempt) {
        if (!referenceName.test(name)) throw new PageError("参考图文件名无效。");
        if (!trackedUpload || trackedUpload.attempt !== attempt || trackedUpload.name !== name) {
            trackedUpload = { name, attempt };
        }
        const record = trackedUpload;
        let state = "pending";
        const dialog = rightsDialog();
        const copies = tiles().filter(t => t.label === name && !t.el.querySelector("flow-error-tile"));
        if (copies.some(t => t.el.querySelector("[data-media-id]") && !/\d+%/.test(t.el.innerText))) state = "uploaded";
        else if (dialog) {
            state = "rights";
            if (dialog !== record.dialog) {
                record.dialog = dialog;
                record.agreed = false;
                dialog.addEventListener("click", event => {
                    const button = event.target.closest?.('button,[role="button"]');
                    if (button && button === control("button", /^(I agree|我同意|同意)$/i, dialog)) record.agreed = true;
                }, true);
            }
        } else if (copies.length) {
            // Flow shows the filename and a percentage before it assigns a media ID.
            const progress = copies.map(t => t.el.innerText.match(/(\d+)%/)?.[1]).find(v => v !== undefined);
            return { state: "transferring", progress, documentId: performance.timeOrigin };
        } else if (record.dialog && !record.agreed) {
            // Cancel, Escape and backdrop dismissal all stop this attempt.
            state = "cancelled";
        }
        return { state, documentId: performance.timeOrigin };
    }
    async function upload({ name, attempt, bytes }) {
        if (uploadState(name, attempt).state !== "pending") return false;
        await useProjectComposer();
        const type = { png: "image/png", jpg: "image/jpeg", webp: "image/webp" }[name.split(".").pop()];
        const raw = Uint8Array.from(atob(bytes), (c) => c.charCodeAt(0));
        const transfer = new DataTransfer();
        transfer.items.add(new File([raw], name, { type }));
        const drop = [...document.querySelectorAll(".ProseMirror[contenteditable=true]")].find(visible);
        if (drop) {
            for (const event of ["dragenter", "dragover", "drop"]) {
                drop.dispatchEvent(
                    new DragEvent(event, { bubbles: true, cancelable: true, dataTransfer: transfer })
                );
            }
        } else {
            const fileInput = () => {
                const inputs = [...document.querySelectorAll("input[type=file]")].filter(el =>
                    !el.disabled && (!el.accept || /image|\.(png|jpg|jpeg|webp)/i.test(el.accept))
                );
                return inputs.length === 1 && inputs[0];
            };
            let input = fileInput();
            if (!input) {
                await click("button", "Add media menu");
                await click("menuitem", "Upload");
                input = await waitFor(() => rightsDialog() || fileInput(), "Flow 没有提供可用的图片上传位置。");
                if (uploadState(name, attempt).state !== "pending") return false;
            }
            input.files = transfer.files;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
        }
        uploadState(name, attempt);
        return true;
    }
    async function radio(name) {
        const el = await need("radio", name);
        if (!el.checked && el.getAttribute("aria-checked") !== "true") el.click();
    }
    async function useProjectComposer() {
        const panel = document.querySelector("flow-agent-panel");
        const close = panel && control("button", /^(Close|关闭|關閉)$/i, panel);
        const agentToggle = () => control("button", /^(Flow )?Agent$/i);
        if (close) {
            close.click();
            await waitFor(() => agentToggle() || control("button", "Settings trigger"), "Flow 项目生成面板未展开。");
        }
        const agent = agentToggle();
        if (agent?.getAttribute("aria-pressed") === "true") {
            agent.click();
            await need("button", "Settings trigger");
        }
    }
    async function configure(job) {
        const model = Object.hasOwn(models, job.model) && models[job.model];
        if (!model) throw new PageError("此扩展版本尚不支持所选模型。");
        await useProjectComposer();
        control("button", "Clear prompt")?.click();
        await click("button", "Settings trigger");
        await radio(job.action === "video" ? "Video" : "Image");
        if (job.action === "video") await radio("Ingredients");
        const option = await need("button", "Select model family");
        if (!model.test(option.innerText)) {
            option.click();
            await click("menuitem", model);
        }
        await radio(job.ratio);
        if (job.action === "video") {
            const length = control("slider", "Length");
            if (length) {
                if (length instanceof HTMLInputElement) {
                    const value = Number(length.min || 0) + 5 * Number(length.step || 1);
                    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(
                        length,
                        String(value)
                    );
                    length.dispatchEvent(new Event("input", { bubbles: true }));
                    length.dispatchEvent(new Event("change", { bubbles: true }));
                } else {
                    key(length, "Home");
                    for (let i = 0; i < 5; i++) key(length, "ArrowRight");
                }
                await waitFor(
                    () =>
                        /(?:Length|时长|長度)\s*8\s*(?:Sec|秒)/i.test(
                            length.closest(".cdk-overlay-pane")?.innerText || ""
                        ),
                    "Flow 未确认 8 秒时长，镜头尚未提交。",
                    2000
                );
            } else await radio("8s");
        }
        await radio("x1");
        key(document.activeElement, "Escape");
        if (control("button", "Select model family")) await click("button", "Settings trigger");
    }
    async function prepare(job) {
        await configure(job);
        const editor = await waitFor(
            () => [...document.querySelectorAll(".ProseMirror[contenteditable=true]")].find(visible),
            "找不到 Flow 提示框。"
        );
        fill(editor, job.prompt.replace(/[\r\n]+/g, " ").trim());
        for (const name of job.references) {
            if (!referenceName.test(name)) throw new PageError("参考图名称无效。");
            await click("button", "Add ingredients to the prompt box");
            const list = await waitFor(
                () => [...document.querySelectorAll("[role=listbox]")].find(visible),
                "找不到素材列表。"
            );
            const picker = list.closest("flow-add-menu-popover-content,.cdk-overlay-pane,[role=dialog]") || document;
            control("tab", "Uploads", picker)?.click();
            const match = new RegExp("^" + name.replace(".", "\\."), "i");
            // A user can have several copies of the same content-addressed file in their project.
            const option = () => matchingControls("option", match, list)[0];
            if (!option()) {
                const search = control("textbox", /^(Search assets|搜索素材|搜尋素材)$/i, picker)
                    || control("textbox", /search|搜索|搜尋/i, picker);
                if (search) fill(search, name);
            }
            const selected = await waitFor(option, "Flow 素材列表中找不到这张参考图。", 7000, "missing_reference");
            selected.click();
            control("button", "Add to prompt", picker)?.click();
            await waitFor(() => !visible(list), "素材选择未完成。");
        }
        const count = document.querySelectorAll(
            'button[aria-label="Ingredient"],[role=button][aria-label="Ingredient"]'
        ).length;
        if (count !== job.references.length) throw new PageError("提示框内的参考图片数与镜头方案不符。");
    }
    const norm = (s) => s.replace(/\s+/g, " ").trim();
    function allowedSource(address) {
        try {
            const u = new URL(address, location.href);
            return (
                !u.username &&
                !u.password &&
                ((u.origin === location.origin && ["blob:", "https:"].includes(u.protocol)) ||
                    (u.protocol === "https:" &&
                        !u.port &&
                        (u.hostname === "storage.googleapis.com" ||
                            /(^|\.)(googleusercontent\.com|googlevideo\.com)$/.test(u.hostname))))
            );
        } catch {
            return false;
        }
    }
    function originalSource(root, kind, detail = false) {
        const link = root.querySelector("a[download][href]");
        if (link && allowedSource(link.href)) return link.href;
        if (kind === "video") {
            const video = root.querySelector("video");
            return video?.currentSrc || video?.src || video?.querySelector("source[src]")?.src;
        }
        const images = [...root.querySelectorAll("img")].filter(
            (el) => !/avatar|icon|logo/i.test(el.alt) && (detail || !/thumb|缩略|縮圖/i.test(el.alt))
        );
        return images.length === 1 && (images[0].currentSrc || images[0].src);
    }
    async function result({ id, kind, handle }) {
        const tile = tiles().find((t) => t.id === id && t.kind === kind);
        if (!tile) throw new PageError("在项目里找不到本次生成结果。");
        tile.el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        let url = originalSource(tile.el, kind);
        if (!url) {
            const before = new Set([...document.querySelectorAll("[role=dialog],dialog[open]")].filter(visible));
            (control("button", /^(play|preview|播放|预览)$/i, tile.el) || tile.el).click();
            url = await waitFor(
                () => {
                    const dialog = [...document.querySelectorAll("[role=dialog],dialog[open]")].find(
                        (d) => visible(d) && !before.has(d)
                    );
                    return originalSource(tile.el, kind) || (dialog && originalSource(dialog, kind, true));
                },
                "无法取得该结果的媒体文件，请在 Flow 项目查看原片。",
                10000
            );
        }
        if (!allowedSource(url)) throw new PageError("Flow 结果没有可读取的 Google 媒体地址。");
        let blob;
        try {
            const res = await fetch(url, {
                credentials: "same-origin",
                redirect: "error",
                signal: AbortSignal.timeout(60000)
            });
            if (!res.ok) throw Error();
            blob = await res.blob();
        } catch {
            return { url };
        } // The worker can fetch a signed Google CDN URL using its host permissions.
        if (!blob.size || blob.size > 120 * 1024 * 1024)
            throw new PageError("Flow 返回的文件为空或超过 120 MiB。");
        retained = { handle, blob };
        return { size: blob.size };
    }
    async function command(m) {
        if (m.op === "probe") return true;
        if (m.op === "chunk") {
            if (retained?.handle !== m.handle || !Number.isSafeInteger(m.offset) || m.offset < 0)
                throw new PageError("媒体读取已中断。");
            const data = new Uint8Array(await retained.blob.slice(m.offset, m.offset + 384 * 1024).arrayBuffer());
            let text = "";
            for (let i = 0; i < data.length; i += 24576)
                text += btoa(String.fromCharCode(...data.subarray(i, i + 24576)));
            return text;
        }
        if (m.op === "release") {
            if (retained?.handle === m.handle) retained = null;
            return;
        }
        if (m.op === "inventory") return inventory();
        if (m.op === "uploadState") return uploadState(m.name, m.attempt);
        switch (m.op) {
            case "new":
                return click("button", /(?:New project|新建项目|新專案|新建專案)$/i);
            case "rename": {
                const el = await need("textbox", "Editable text");
                fill(el, m.title.slice(0, 110));
                key(el, "Enter");
                el.blur();
                return;
            }
            case "upload":
                return upload(m);
            case "prepare":
                await prepare(m.job);
                return inventory();
            case "submit": {
                const box = document.querySelector(".ProseMirror[contenteditable=true]");
                const copy = box?.cloneNode(true);
                copy?.querySelectorAll('[contenteditable=false],[aria-label="Ingredient"]').forEach((el) =>
                    el.remove()
                );
                const count = document.querySelectorAll(
                    'button[aria-label="Ingredient"],[role=button][aria-label="Ingredient"]'
                ).length;
                if (!copy || norm(copy.textContent) !== norm(m.prompt) || count !== m.referenceCount) {
                    throw new PageError("提示词或参考图已变更，镜头尚未提交。", "unsubmitted");
                }
                const start = await need("button", "Start generation");
                if (start.disabled || start.getAttribute("aria-disabled") === "true")
                    throw new PageError("生成按钮不可用。", "unsubmitted");
                start.click();
                return;
            }
            case "result":
                return result(m);
            default:
                throw new PageError("未知的 Flow 操作。");
        }
    }
    chrome.runtime.onMessage.addListener((m, sender, reply) => {
        if (sender.id !== chrome.runtime.id || m?.channel !== channel || window !== window.top) return;
        command(m)
            .then((value) => reply({ ok: true, value }))
            .catch((err) =>
                reply({
                    ok: false,
                    kind: err.kind || "page",
                    error: err instanceof PageError ? err.message : "Flow 页面操作未完成，请检查此标签页。"
                })
            );
        return true;
    });
})();
