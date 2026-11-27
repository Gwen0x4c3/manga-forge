# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.49,<2"]
# ///
"""MangaForge desktop connector. Run on the computer with Google Chrome and Python 3.10+.

Install Playwright with: python -m pip install playwright
Run: python mangaforge_flow.py
Pass --pair to replace the MangaForge pairing or --login to sign into Chrome again.
The connector only drives visible Google Flow controls. No Google credentials enter its API protocol.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

FLOW = "https://flow.google.com/"
MODELS = {
    "veo-3.1-lite": r"veo\s*3\.1\s*[-–·]?\s*lite",
    "omni-flash-1.2": r"omni\s*(?:flash\s*1\.2|1\.2\s*flash)",
    "nano-banana-2-lite": r"nano banana 2 lite",
    "nano-banana-2": r"nano banana 2(?:\.1)?(?![.\d]|\s*lite)",
    "nano-banana-pro": r"nano banana pro",
}
DATA = Path.home() / ".mangaforge-flow"
PROFILE = DATA / "chrome"
TILES = "flow-grid-tile-container"


class FlowBrowserError(Exception):
    """Only these bounded, locally authored messages may be returned to MangaForge."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def parse_pair(value: str) -> tuple[str, str]:
    url = urlsplit(value.strip())
    local = url.hostname == "localhost"
    try:
        local |= ipaddress.ip_address(url.hostname or "").is_private
    except ValueError:
        pass
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or not (url.scheme == "https" or url.scheme == "http" and local)
        or not re.fullmatch(r"/api/v1/flow/browsers/[0-9a-f-]{36}", url.path)
        or not re.fullmatch(r"[\w-]{25,100}", url.fragment)
    ):
        raise FlowBrowserError("配对串无效。请从自己的 MangaForge 模型中心复制完整配对串。")
    return urlunsplit((url.scheme, url.netloc, url.path, "", "")), url.fragment


class MangaForge:
    def __init__(self, endpoint: str, token: str):
        self.endpoint, self.token, self.runner = endpoint, token, str(uuid.uuid4())
        self.http = build_opener(ProxyHandler({}), NoRedirect())

    def _send(self, route, method, data, content_type, raw):
        headers = {"Content-Type": content_type, "X-Flow-Runner": self.runner}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        with self.http.open(Request(self.endpoint + route, data=data, headers=headers, method=method), timeout=45) as r:
            body = r.read()
            if raw:
                return body
            result = json.loads(body)
            return result["data"] if "code" in result else result

    async def send(self, route, value=None, *, method="POST", raw=False, media=None):
        data = media if media is not None else json.dumps(value or {}).encode() if method == "POST" else None
        mime = "application/octet-stream" if media is not None else "application/json"
        return await asyncio.to_thread(self._send, route, method, data, mime, raw)


def chrome():
    candidates = [
        os.environ.get("MANGAFORGE_CHROME"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.environ.get(root):
            candidates.append(str(Path(os.environ[root]) / "Google/Chrome/Application/chrome.exe"))
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise FlowBrowserError("未找到 Google Chrome。请安装 Chrome 或设置 MANGAFORGE_CHROME 为可执行文件路径。")


def is_flow(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and (
        p.netloc in {"flow.google.com", "flow.google"}
        or p.netloc == "labs.google"
        and bool(re.match(r"^/fx/(?:[\w-]+/)?tools/flow(?:/|$)", p.path))
    )


async def signed_in(page):
    if not is_flow(page.url):
        return False
    for name in ("New project", "Account details", "Settings trigger"):
        if await page.get_by_role("button", name=name, exact=True).first.is_visible():
            return True
    return False


async def open_project(page, project):
    project = str(uuid.UUID(project))
    if not (is_flow(page.url) and urlsplit(page.url).path.rstrip("/").endswith("/project/" + project)):
        await page.goto(FLOW + "project/" + project + "?hl=en", wait_until="domcontentloaded")
    await page.get_by_role("button", name="Settings trigger", exact=True).wait_for(timeout=25000)
    if not is_flow(page.url) or not urlsplit(page.url).path.rstrip("/").endswith("/project/" + project):
        raise FlowBrowserError("当前 Google 账号无法打开本话的 Flow 项目。")


async def create_project(page, title, memo, save):
    if memo.get("project"):
        await open_project(page, memo["project"])
    else:
        await page.goto(FLOW + "?hl=en", wait_until="domcontentloaded")
        await page.get_by_role("button", name="New project", exact=True).click()
        await page.wait_for_url(re.compile(r"/project/[0-9a-f-]{36}"), timeout=30000)
        if not is_flow(page.url):
            raise FlowBrowserError("未打开 Google Flow 项目。")
        memo["project"] = str(uuid.UUID(urlsplit(page.url).path.rstrip("/").split("/")[-1]))
        save()
    name = page.get_by_role("textbox", name="Editable text", exact=True).first
    await name.fill(title[:110])
    await name.press("Enter")
    return {"project": memo["project"]}


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise FlowBrowserError("Flow 网页只接收 PNG、JPEG 或 WebP 参考图。")


async def upload(page, data, digest):
    if hashlib.sha256(data).hexdigest() != digest:
        raise FlowBrowserError("素材内容已变更，请重新读取本话的镜头方案。")
    ext, mime = image_type(data)
    name = f"mf-{digest}.{ext}"
    tile = page.locator(f'{TILES}[aria-label="{name}"]:has([data-media-id])').first
    if not await tile.count():
        await page.get_by_role("button", name="Add media menu").click()
        async with page.expect_file_chooser() as picker:
            await page.get_by_role("menuitem", name="Upload", exact=True).click()
        await (await picker.value).set_files({"name": name, "mimeType": mime, "buffer": data})
        await tile.wait_for(state="attached", timeout=90000)
    return {"name": name}


async def set_option(page, label):
    radio = page.get_by_role("radio", name=label, exact=True).first
    if not await radio.is_checked():
        await radio.click()


async def configure(page, action, model, ratio):
    if model not in MODELS:
        raise FlowBrowserError("本地连接器不支持所选 Flow 模型。")
    agent = page.get_by_role("button", name=re.compile(r"^(Flow )?Agent$")).first
    if await agent.is_visible() and await agent.get_attribute("aria-pressed") == "true":
        await agent.click()
    clear = page.get_by_role("button", name="Clear prompt", exact=True)
    if await clear.is_visible():
        await clear.click()
    trigger = page.get_by_role("button", name="Settings trigger", exact=True)
    await trigger.click()
    await set_option(page, "Video" if action == "video" else "Image")
    if action == "video":
        await set_option(page, "Ingredients")
    model_button = page.get_by_role("button", name="Select model family", exact=True)
    model_name = re.compile(MODELS[model], re.I)
    if not model_name.search(await model_button.inner_text()):
        await model_button.click()
        item = page.get_by_role("menuitem", name=model_name)
        await item.first.wait_for()
        if await item.count() != 1:
            raise FlowBrowserError("Flow 中所选模型名称不唯一，请检查模型菜单。")
        await item.click()
    await set_option(page, ratio)
    if action == "video":
        slider = page.get_by_role("slider", name="Length", exact=True)
        if await slider.is_visible():
            await slider.press("Home")
            for _ in range(5):
                await slider.press("ArrowRight")
            pane = page.locator(".cdk-overlay-pane").filter(has=slider).last
            if not re.search(r"Length\s*8\s*Sec", await pane.inner_text(), re.I):
                raise FlowBrowserError("Flow 时长未设为 8 秒，镜头尚未提交。")
        else:
            await set_option(page, "8s")
    await set_option(page, "x1")
    await page.keyboard.press("Escape")
    if await model_button.is_visible():
        await trigger.click()


async def attach(page, names):
    for name in names:
        if not re.fullmatch(r"mf-[a-f0-9]{64}\.(png|jpg|webp)", name):
            raise FlowBrowserError("参考图文件名无效。")
        await page.get_by_role("button", name="Add ingredients to the prompt box", exact=True).click()
        listing = page.get_by_role("listbox", name="Asset list")
        tab = page.get_by_role("tab", name="Uploads", exact=True)
        if await tab.is_visible():
            await tab.click()
        option = listing.get_by_role("option", name=re.compile("^" + re.escape(name), re.I)).first
        if not await option.count():
            search = page.get_by_role("textbox", name=re.compile("search", re.I)).last
            if await search.is_visible():
                await search.fill(name)
        await option.click()
        add = page.get_by_role("button", name="Add to prompt", exact=True)
        if await add.is_visible():
            await add.click()
        await listing.wait_for(state="hidden", timeout=10000)
    if await page.get_by_role("button", name="Ingredient", exact=True).count() != len(names):
        raise FlowBrowserError("Flow 提示框的参考图数量与镜头方案不符，尚未提交。")


async def tiles(page):
    return await page.locator(TILES).evaluate_all("""els => els.map(t => {
        const label = t.getAttribute('aria-label') || '';
        const kind = t.querySelector('flow-video-tile') ? 'video' : t.querySelector('flow-image-tile') ? 'image' : '';
        return {label, kind, id: t.querySelector('[data-media-id]')?.getAttribute('data-media-id') || label,
            ready: !label.startsWith('mf-') && !/\\d+%/.test(t.innerText) &&
                   !!t.querySelector(kind === 'video' ? 'video,img[alt="Generated video thumbnail"]' : 'img[src]')};
    })""")


async def download(page, label, target):
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    # Use Chrome's download event from the selected tile. Never scan the user's Downloads directory.
    tile = page.locator(TILES).and_(page.locator("[aria-label=" + json.dumps(label, ensure_ascii=False) + "]")).first
    await tile.hover()
    more = tile.get_by_role("button", name="More options", exact=True)
    if await more.is_visible():
        await more.click()
    else:
        await tile.click(button="right")
    async with page.expect_download(timeout=120000) as item:
        await page.get_by_role("menuitem", name="Download", exact=True).click()
        original = page.get_by_role("menuitem", name=re.compile("original", re.I)).first
        try:
            await original.wait_for(timeout=2200)
        except PlaywrightTimeout:
            pass
        else:
            await original.click()
    artifact = await item.value
    tmp = target.with_suffix(".part")
    await artifact.save_as(tmp)
    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as archive:
            exts = {".mp4"} if target.suffix == ".mp4" else {".png", ".jpg", ".jpeg", ".webp"}
            items = [i for i in archive.infolist() if Path(i.filename).suffix.lower() in exts and not i.is_dir()]
            if len(items) != 1 or items[0].file_size > 120 * 1024 * 1024:
                raise FlowBrowserError("Flow 下载包未包含单个预期媒体文件，请在项目里核对。")
            raw = archive.read(items[0])
        tmp.write_bytes(raw)
    with tmp.open("rb") as f:
        magic = f.read(16)
    if target.suffix == ".mp4" and magic[4:8] != b"ftyp":
        raise FlowBrowserError("Flow 下载的文件不是 MP4。原镜头仍在 Flow 项目内。")
    if target.suffix != ".mp4":
        image_type(magic)
    tmp.replace(target)


async def generate(page, job, memo, save, target, permit):
    action = job["action"]
    if "before" not in memo:
        if job.get("redelivered") and not memo.get("prepared"):
            raise FlowBrowserError("本次已领取任务缺少本地记录，请先在 Flow 核对镜头。")
        memo["prepared"] = True
        save()
        await configure(page, action, job["model"], job["ratio"])
        await attach(page, job["references"])
        prompt = " ".join(job["prompt"].splitlines()).strip()
        box = page.locator(".ProseMirror[contenteditable=true]").first
        await box.click()
        await box.press("ControlOrMeta+a")
        await page.keyboard.insert_text(prompt)
        start = page.get_by_role("button", name="Start generation", exact=True)
        if not await start.is_enabled():
            raise FlowBrowserError("Flow 生成按钮不可用，请检查素材和账号积分。")
        # Flush before the only credit-consuming click. Redelivery can download or observe, never submit twice.
        if (await permit()).get("status") != "running":
            raise FlowBrowserError("任务已结束，未提交生成。")
        memo["before"] = [t["id"] for t in await tiles(page)]
        memo["errors"] = await page.locator("flow-error-tile").count()
        save()
        await start.click()
    deadline = time.monotonic() + 900
    while not memo.get("tile"):
        fresh = [
            t
            for t in await tiles(page)
            if t["kind"] == action and t["ready"] and t["id"] and t["id"] not in memo["before"]
        ]
        if len(fresh) > 1:
            raise FlowBrowserError("Flow 同时出现多个结果，无法确认哪一个对应当前镜头。请在项目里核对。")
        if fresh:
            memo["tile"] = fresh[0]["label"]
            save()
            break
        if await page.locator("flow-error-tile").count() > memo["errors"]:
            raise FlowBrowserError("Google Flow 提示生成失败。请在该项目查看原因和积分记录。")
        if time.monotonic() > deadline:
            raise FlowBrowserError("Flow 尚未返回镜头，提交结果待核对。")
        await asyncio.sleep(2)
    await download(page, memo["tile"], target)


async def run_job(api, page, job, folder):
    jid = str(uuid.UUID(job["id"]))
    prefix = "/jobs/" + jid
    journal = folder / (jid + ".json")
    memo = json.loads(journal.read_text()) if journal.exists() else {}
    target = folder / (jid + (".mp4" if job["action"] == "video" else ".img"))

    def save():
        atomic_write(journal, json.dumps(memo).encode())

    if not memo.get("reply") and not target.exists():
        try:
            if job["action"] == "project":
                memo["reply"] = await create_project(page, job["title"], memo, save)
            else:
                await open_project(page, job["project"])
                if job["action"] == "upload":
                    raw = await api.send(prefix + "/inputs/0", method="GET", raw=True)
                    memo["reply"] = await upload(page, raw, job["digest"])
                elif job["action"] in {"image", "video"}:
                    await generate(page, job, memo, save, target, lambda: api.send(prefix + "/heartbeat"))
                else:
                    raise FlowBrowserError("未知的浏览器任务。")
        except (HTTPError, URLError):
            raise
        except Exception as exc:
            uncertain = "before" in memo or (job["redelivered"] and not memo.get("prepared"))
            message = (
                str(exc)
                if isinstance(exc, FlowBrowserError)
                else "Flow 网页操作未完成。请检查专用窗口中的登录、弹窗和页面控件。"
            )
            memo["reply"] = {"error": message, "uncertain": uncertain and job["action"] in {"video", "image"}}
        save()
    if target.exists():
        try:
            await api.send(prefix + "/media", method="PUT", media=target.read_bytes())
        except HTTPError as exc:
            if exc.code not in {413, 422}:
                raise
            await api.send(
                prefix + "/finish",
                {"error": "下载的媒体未通过 MangaForge 核验，请在 Flow 项目核对原片。", "uncertain": True},
            )
        target.unlink(missing_ok=True)
    else:
        await api.send(prefix + "/finish", memo["reply"])
    # The server accepted the result before the local journal is discarded.
    journal.unlink(missing_ok=True)


async def keepalive(api, jid):
    while True:
        await asyncio.sleep(14)
        await api.send("/jobs/" + jid + "/heartbeat")


async def serve(api, playwright, folder):
    context = await playwright.chromium.launch_persistent_context(
        str(PROFILE),
        executable_path=chrome(),
        headless=False,
        accept_downloads=True,
        locale="en-US",
    )
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(9000)
        await page.goto(FLOW + "?hl=en", wait_until="domcontentloaded")
        print("连接器已启动。请保留此终端和专用 Chrome 窗口。按 Ctrl+C 可退出。")
        while not page.is_closed():
            try:
                result = await api.send("/next", {"ready": await signed_in(page)})
                job = result.get("job")
                if not job:
                    await asyncio.sleep(3)
                    continue
                heart = asyncio.create_task(keepalive(api, job["id"]))
                try:
                    await run_job(api, page, job, folder)
                finally:
                    heart.cancel()
                    await asyncio.gather(heart, return_exceptions=True)
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise FlowBrowserError("配对已失效，请用 --pair 重新配对本机。") from None
                print(f"MangaForge HTTP {exc.code}，等待重新连接。")
                await asyncio.sleep(7)
            except (URLError, OSError):
                await asyncio.sleep(7)
    finally:
        await context.close()


async def main():
    from playwright.async_api import async_playwright

    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--pair", action="store_true")
    args.add_argument("--login", action="store_true")
    options = args.parse_args()
    DATA.mkdir(exist_ok=True, parents=True, mode=0o700)
    config = DATA / "pair.json"
    if options.pair or not config.exists():
        endpoint, code = parse_pair(getpass.getpass("粘贴自己 MangaForge 模型中心的完整配对串（输入隐藏）："))
        print("配对 MangaForge 主机", urlsplit(endpoint).netloc)
        api = MangaForge(endpoint, "")
        result = await api.send("/connect", {"code": code})
        atomic_write(config, json.dumps({"endpoint": endpoint, "token": result["token"]}).encode())
    settings = json.loads(config.read_text())
    if options.login or not PROFILE.exists():
        PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.Popen(
            [chrome(), f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check", FLOW + "?hl=en"]
        )
        input("请在新打开的 Chrome 窗口登录自己的 Google Ultra 账号。进入 Flow 后关闭这个专用窗口，再按回车。")
    api = MangaForge(settings["endpoint"], settings["token"])
    folder = DATA / "jobs" / hashlib.sha256(api.token.encode()).hexdigest()[:20]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as pw:
        await serve(api, pw, folder)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except ImportError:
        sys.exit("请先运行 python -m pip install playwright")
    except (FlowBrowserError, HTTPError, URLError) as exc:
        sys.exit(str(exc) if isinstance(exc, FlowBrowserError) else "无法连接自己的 MangaForge，请检查配对串和网络。")
