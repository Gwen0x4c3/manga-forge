import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from app.core.image_backend import get_image_backend
from app.core.provider_runtime import ResolvedModelConfig
from app.database import Base, get_db
from app.models import (
    Asset,
    AssetImage,
    Branch,
    Episode,
    EpisodeMemory,
    EpisodePage,
    FlowBrowser,
    FlowBrowserJob,
    FlowExtensionKey,
    GenerationRun,
    ModelProvider,
    ModelRoleBinding,
    Project,
)
from app.providers import google_flow as browser
from app.providers.flow_desktop import FlowBrowserError, is_flow, parse_pair
from app.providers.google_flow import FlowError
from app.routers import flow as flow_routes
from app.routers import flow_browser
from app.schemas.google_flow import FlowOptions, FlowStart
from app.schemas.provider import ProviderCreateRequest, ProviderTestRequest
from app.services import flow_video, provider_service
from app.services.flow_plan import build_plan
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_provider_hub import _AsyncSessionAdapter


class TestSession(_AsyncSessionAdapter):
    __test__ = False

    async def get(self, entity, ident, **kwargs):
        return self._s.get(entity, ident, **kwargs)

    async def rollback(self):
        self._s.rollback()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield TestSession(s)


def png(color):
    out = io.BytesIO()
    Image.new("RGB", (20, 30), color).save(out, format="PNG")
    return out.getvalue()


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node for the Ego browser SDK fixture")
def test_ego_profile_account_and_interrupted_submission():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("ego_connector.mjs"))], check=True, timeout=35)


@pytest.mark.skipif(not shutil.which("node"), reason="requires Node for the extension content script")
def test_extension_uses_manual_flow_session():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("flow_extension.mjs"))], check=True, timeout=10)


async def add_browser(db):
    p = await provider_service.create_provider(db, ProviderCreateRequest(preset_key=browser.PRESET, name="Ultra"))
    assert p.flow_status == "unpaired" and not p.has_api_key and p.base_url == browser.FLOW_URL
    assert not (await db.get(ModelProvider, p.id)).api_key_encrypted
    return p


async def pair(http, pid):
    base = f"/browsers/{pid}"
    code = (await http.post(base + "/pair")).json()["code"]
    res = await http.post(base + "/connect", json={"code": code})
    assert res.status_code == 200, res.text
    assert (await http.post(base + "/connect", json={"code": code})).status_code == 403
    headers = {"Authorization": "Bearer " + res.json()["token"], "X-Flow-Runner": str(uuid4())}
    assert (await http.post(base + "/next", headers=headers, json={"ready": True})).is_success
    return headers


def web(db):
    app = FastAPI()
    app.include_router(flow_browser.router)
    app.include_router(flow_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[flow_routes.get_db] = lambda: db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_extension_token_activates_once_without_legacy_pairing_and_is_revocable(db):
    p = await add_browser(db)
    base = f"/browsers/{p.id}"
    management = {"X-MangaForge-Manage": "flow-extension"}
    async with web(db) as http:
        old = await pair(http, p.id)
        assert (await http.post(base + "/extension-token")).status_code == 403
        issue = await http.post(base + "/extension-token", headers=management)
        assert issue.headers["cache-control"] == "no-store"
        token = issue.json()["token"]
        row = await db.get(FlowExtensionKey, p.id)
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert (await http.get(base + "/extension-token")).json() == {"issued": True}
        assert (await http.post(base + "/presence", headers=old, json={"ready": True})).is_success
        runner = {"Authorization": "Bearer " + token, "X-Flow-Runner": str(uuid4())}
        assert (await http.post(base + "/next", headers=runner, json={"ready": True})).status_code == 403
        bind = await http.post("/extension/connect", headers=runner)
        assert bind.is_success and bind.json()["provider_id"] == p.id
        assert row.account_hash is None
        # An existing 1.0 installation keeps its token, session and jobs when upgrading.
        row.account_hash = "a" * 64
        await db.commit()
        for body in ({"account_hash": "b" * 64}, {}):
            assert (await http.post("/extension/connect", headers=runner, json=body)).json() == bind.json()
            assert row.account_hash is None
        assert (await http.post(base + "/next", headers=old, json={"ready": True})).status_code == 403
        wrong = {**runner, "X-Flow-Runner": str(uuid4())}
        assert (await http.post("/extension/connect", headers=wrong)).status_code == 409
        assert (await http.post(base + "/next", headers=wrong, json={"ready": True})).status_code == 403
        assert (await http.post(base + "/next", headers=runner, json={"ready": True})).is_success
        assert (await http.delete(base + "/extension-token", headers=management)).status_code == 204
        assert (await http.post("/extension/connect", headers=runner)).status_code == 403
        assert (await http.post(base + "/next", headers=runner, json={"ready": True})).status_code == 403


@pytest.mark.asyncio
async def test_extension_zip_has_all_manifest_entries_and_activation_preserves_active_work(db):
    p = await add_browser(db)
    base = f"/browsers/{p.id}"
    async with web(db) as http:
        package = await http.get("/extension.zip", params={"server": "https://manga.example.test"})
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["manifest_version"] == 3
            assert manifest["homepage_url"] == "https://manga.example.test/"
            assert not {"debugger", "cookies", "downloads"}.intersection(manifest["permissions"])
            entries = [manifest["action"]["default_popup"], manifest["background"]["service_worker"],
                       *manifest["content_scripts"][0]["js"], "protocol.js", "popup.js", "popup.css"]
            assert all(name in archive.namelist() for name in entries)
        old = await pair(http, p.id)
        device = await db.get(FlowBrowser, p.id)
        await browser.enqueue(db, p.id, device.session_id, "image", "test", {})
        await db.commit()
        issued = await http.post(base + "/extension-token", headers={"X-MangaForge-Manage": "flow-extension"})
        headers = {"Authorization": "Bearer " + issued.json()["token"], "X-Flow-Runner": str(uuid4())}
        busy = await http.post("/extension/connect", headers=headers, json={"account_hash": "f" * 64})
        assert busy.status_code == 409
        assert (await http.post(base + "/next", headers=old, json={"ready": True})).json()["job"]["action"] == "image"


@pytest.mark.asyncio
async def test_extension_accepts_a_single_flow_image_in_a_download_archive(db, monkeypatch):
    p = await add_browser(db)
    base = f"/browsers/{p.id}"
    saved = {}
    monkeypatch.setattr(flow_video.storage_service, "upload_file", lambda _, key, data, mime: saved.update({key: data}))
    async with web(db) as http:
        headers = await pair(http, p.id)
        device = await db.get(FlowBrowser, p.id)
        job = await browser.enqueue(db, p.id, device.session_id, "image", "archived", {})
        await db.commit()
        await http.post(base + "/next", headers=headers, json={"ready": True})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("creation.png", png("red"))
        res = await http.put(f"{base}/jobs/{job.id}/media", headers=headers, content=buf.getvalue())
        assert res.json() == {"status": "succeeded"}
        with Image.open(io.BytesIO(next(iter(saved.values())))) as image:
            assert image.getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.asyncio
async def test_pairing_and_legacy_never_forward_keys(db, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("unexpected outbound HTTP")

    p = await add_browser(db)
    for key in (browser.PRESET, browser.LEGACY):
        with pytest.raises(FlowError):
            await provider_service.create_provider(
                db, ProviderCreateRequest(preset_key=key, name="X", api_key="secret")
            )
    req = ProviderTestRequest(provider_id=p.id, api_key="google-key", base_url="https://outside.invalid")
    async with web(db) as http:
        old = await pair(http, p.id)
        with monkeypatch.context() as guard:
            guard.setattr(httpx, "AsyncClient", no_network)
            assert (await provider_service.test_provider(db, req)).ok
            assert not (await provider_service.test_provider(db, ProviderTestRequest(preset_key=browser.LEGACY))).ok
        await pair(http, p.id)
        assert (await http.post(f"/browsers/{p.id}/next", headers=old, json={"ready": True})).status_code == 403
        row = await db.get(FlowBrowser, p.id)
        assert row.token_hash != old["Authorization"][7:]
        code = await browser.pair_code(db, p.id)
        row.pair_until = browser.now() - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(FlowError):
            await browser.connect(db, p.id, code)


@pytest.mark.asyncio
async def test_sync_and_generate_ordered_shots_with_recovery(db, monkeypatch, tmp_path):
    p = await add_browser(db)
    ep = Episode(id="ep", project_id="p", branch_id="b", label="1", number=1)
    db._s.add_all([Project(id="p", title="星光"), Branch(id="b", name="main", project_id="p"), ep])
    db._s.add_all([EpisodePage(episode_id="ep", page_index=n - 1, image_path=str(n)) for n in (3, 1, 2)])
    db._s.add_all(
        [
            Asset(id="a", project_id="p", name="小风", type="character", episode_ids={"ep": True}),
            AssetImage(asset_id="a", image_path="ref", kind="reference", meta={"is_primary": True}),
            EpisodeMemory(
                episode_id="ep",
                type="summary",
                content={"page_dialogues": [{"page_number": 1, "lines": [{"speaker": "小风", "text": "我回来了"}]}]},
            ),
        ]
    )
    await db.commit()
    plan = await build_plan(db, ep, FlowOptions())
    assert [s.references for s in plan.shots] == [["1", "2", "ref"], ["3"]]
    assert "我回来了" in plan.shots[0].prompt
    data = {k: png(c) for k, c in zip(["1", "2", "3", "ref"], ["red", "green", "blue", "red"])}
    monkeypatch.setattr(flow_video.storage_service, "get_object_bytes", lambda _, key: data.get(key))
    monkeypatch.setattr(flow_video.storage_service, "upload_file", lambda _, key, raw, mime: data.update({key: raw}))
    frames = []

    async def export(keys, key):
        frames.extend(keys)
        data[key] = b"".join(data[k] for k in keys)

    monkeypatch.setattr(flow_video, "export_video", export)
    base = f"/browsers/{p.id}"
    remote = str(uuid4())
    completed = []
    seen_ids = []
    prompts = []
    async with web(db) as http:
        headers = await pair(http, p.id)
        sync = FlowStart(provider_id=p.id, plan_id=plan.plan_id, mode="sync")
        run, _ = await flow_video.start_run(db, ep, sync)

        async def advance(run, uncertain=False):
            for _ in range(55):
                if await flow_video.advance(db, run.id) is None:
                    return
                claim = await http.post(base + "/next", headers=headers, json={"ready": True})
                job = claim.json().get("job")
                if not job:
                    continue
                action, jid = job["action"], job["id"]
                assert jid not in seen_ids
                seen_ids.append(jid)
                addr = base + "/jobs/" + jid
                assert (await http.post(addr + "/heartbeat", headers=headers)).is_success
                other = {**headers, "X-Flow-Runner": str(uuid4())}
                assert not (await http.post(base + "/next", headers=other, json={"ready": True})).json()["job"]
                if action == "project":
                    assert job["title"] == "星光"
                    res = await http.post(addr + "/finish", headers=headers, json={"project": remote})
                elif action == "upload":
                    raw = (await http.get(addr + "/inputs/0", headers=headers)).content
                    assert job["project"] == remote and hashlib.sha256(raw).hexdigest() == job["digest"]
                    assert (await http.get(addr + "/inputs/1", headers=headers)).status_code == 404
                    link = f"https://flow.google.com/u/1/project/{remote}"
                    progress = {"waiting_for": "upload_rights", "project_url": link}
                    assert (await http.post(addr + "/heartbeat", headers=headers, json=progress)).is_success
                    assert (await http.post(addr + "/heartbeat", headers=headers, json={})).is_success
                    assert await flow_video.advance(db, run.id) > 0
                    assert flow_video.describe(run)["waiting_for"] == "upload_rights"
                    assert flow_video.describe(run)["project_url"] == link
                    assert (await http.post(addr + "/heartbeat", headers=headers, json={"waiting_for": None})).is_success
                    assert await flow_video.advance(db, run.id) > 0
                    assert not flow_video.describe(run)["waiting_for"]
                    res = await http.post(
                        addr + "/finish", headers=headers, json={"name": "mf-" + job["digest"] + ".png", "project_url": link}
                    )
                elif uncertain:
                    res = await http.post(
                        addr + "/finish", headers=headers, json={"error": "请核对", "uncertain": True}
                    )
                else:
                    prompts.append(job["prompt"])
                    assert job["project"] == remote and len(job["references"]) in (1, 2)
                    res = await http.put(addr + "/media", headers=headers, content=b"could be an error page")
                    assert res.status_code == 422
                    res = await http.put(addr + "/media", headers=headers, content=b"0000ftypisom0000" + jid.encode())
                assert res.is_success, res.text
                completed.append(action)
            pytest.fail("Flow run never finished")

        await advance(run)
        assert run.status == "succeeded" and completed == ["project", "upload", "upload", "upload"]
        assert (await flow_video.start_run(db, ep, sync))[1] is False
        video = FlowStart(provider_id=p.id, plan_id=plan.plan_id, prompts=["定制镜头", "结尾"])
        run, _ = await flow_video.start_run(db, ep, video)
        with pytest.raises(FlowError, match="已有"):
            await flow_video.start_run(db, ep, video.model_copy(update={"request_id": uuid4()}))
        await advance(run, uncertain=True)
        assert run.status == "failed" and flow_video.describe(run)["uncertain"]
        with pytest.raises(FlowError, match="确认重试"):
            await flow_video.resume_run(db, ep, run.id)
        other_account = await add_browser(db)
        await pair(http, other_account.id)
        with pytest.raises(FlowError, match="另一个 Flow 连接"):
            await flow_video.resume_run(db, ep, run.id, retry_uncertain=True, provider_id=other_account.id)
        assert run.status == "failed" and run.params["uncertain"]
        assert (await flow_video.resume_run(db, ep, run.id, retry_uncertain=True))[1]
        await advance(run)
        assert run.status == "succeeded" and prompts[0].startswith("定制镜头") and prompts[1:] == ["结尾"]
        assert completed.count("upload") == 3 and completed.count("project") == 1
        assert [s["video_id"] for s in run.params["shots"]] == frames
        assert len(db._s.scalars(select(FlowBrowserJob)).all()) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["new_provider", "new_session"])
async def test_stale_sync_restarts_on_selected_connection_without_image_role(db, monkeypatch, replacement):
    dispatch = Mock()
    monkeypatch.setattr(flow_routes.celery_client, "send_task", dispatch)
    role_lookup = Mock(side_effect=AssertionError("unexpected role lookup"))
    monkeypatch.setattr(provider_service, "resolve_role_config", role_lookup)
    ep = Episode(id="ep", project_id="p", branch_id="b", number=1)
    db._s.add_all([
        Project(id="p", title="星光"),
        Branch(id="b", name="main", project_id="p"),
        ep,
        EpisodePage(episode_id=ep.id, page_index=0, image_path="page.png"),
    ])
    await db.commit()
    old = await add_browser(db)
    async with web(db) as http:
        await pair(http, old.id)
        [original] = (await http.get("/accounts")).json()
        chapter = f"/episodes/{ep.id}"
        plan = (await http.post(chapter + "/plan", json={})).json()
        spec = {
            "mode": "sync",
            "plan_id": plan["plan_id"],
            "provider_id": old.id,
            "connection_id": original["connection_id"],
        }
        assert await db.get(ModelRoleBinding, "image_gen") is None
        run = (await http.post(chapter + "/runs", json=spec)).json()
        await flow_video.advance(db, run["id"])
        stored = await db.get(GenerationRun, run["id"])
        pending = await db.get(FlowBrowserJob, stored.params["pending_job"])
        device = await db.get(FlowBrowser, old.id)
        device.last_seen = pending.created_at = browser.now() - timedelta(minutes=4)
        await db.commit()
        await flow_video.advance(db, stored.id)
        [failed] = (await http.get(chapter + "/runs")).json()
        assert (failed["status"], failed["synced"], failed["connection_id"]) == ("failed", 0, original["connection_id"])

        selected = old
        if replacement == "new_provider":
            assert await provider_service.delete_provider(db, old.id)
            selected = await add_browser(db)
        await pair(http, selected.id)
        image = await provider_service.create_provider(db, ProviderCreateRequest(
            preset_key="antigravity", name="原有作图服务", activate_roles=["image_gen"],
        ))
        [current] = (await http.get("/accounts")).json()
        assert current["status"] == "ready" and current["id"] == selected.id
        assert current["connection_id"] != failed["connection_id"]
        resume_url = chapter + "/runs/" + stored.id + "/resume"
        stale = await http.post(resume_url, params={"provider_id": old.id})
        assert stale.status_code == 409 and "重新同步素材" in stale.json()["detail"]
        if replacement == "new_provider":
            assert (await http.post(resume_url, params={"provider_id": selected.id})).status_code == 409
        wrong_session = await http.post(chapter + "/runs", json={**spec, "provider_id": selected.id})
        assert wrong_session.status_code == 409 and "连接已更新" in wrong_session.json()["detail"]
        assert dispatch.call_count == 1

        fresh = await http.post(chapter + "/runs", json={
            **spec, "provider_id": selected.id, "connection_id": current["connection_id"],
        })
        assert fresh.status_code == 202
        restarted = fresh.json()
        assert restarted["id"] != stored.id and restarted["mode"] == "sync"
        assert restarted["remote_id"] is None and restarted["synced"] == 0
        await flow_video.advance(db, restarted["id"])
        active_run = await db.get(GenerationRun, restarted["id"])
        project_job = await db.get(FlowBrowserJob, active_run.params["pending_job"])
        assert (project_job.action, project_job.provider_id, project_job.session_id) == (
            "project", selected.id, current["connection_id"],
        )
        assert (await db.get(ModelRoleBinding, "image_gen")).provider_id == image.id
        assert stored.status == "failed" and dispatch.call_count == 2


@pytest.mark.asyncio
async def test_flow_image_provider_uses_browser(monkeypatch):
    cfg = ResolvedModelConfig(
        "image_gen", "database", "p", browser.PRESET, "Ultra", browser.PRESET, browser.FLOW_URL, "", "nano-banana-2"
    )
    monkeypatch.setattr("app.core.provider_runtime.resolve_role_config", lambda role: cfg)
    monkeypatch.setattr("app.core.telemetry.record_usage_event", AsyncMock())
    generate = AsyncMock(return_value=png("blue"))
    monkeypatch.setattr(browser, "generate_image", generate)
    refs = [(png("red"), "image/png")]
    result = await get_image_backend().generate("星光", "noise", size=(768, 1024), reference_images=refs)
    pid, model, prompt, ratio, images, _ = generate.await_args.args
    assert (pid, model, ratio, images) == ("p", "nano-banana-2", "3:4", refs)
    assert "noise" in prompt and result.image_data == png("blue")


def test_connector_only_accepts_official_browser_pages_and_scoped_pairing():
    code = "A" * 32
    link = f"http://127.0.0.1:8000/api/v1/flow/browsers/{uuid4()}#{code}"
    assert parse_pair(link) == (link.split("#")[0], code)
    with pytest.raises(FlowBrowserError):
        parse_pair(link.replace("127.0.0.1", "example.org"))
    assert is_flow("https://flow.google.com/project/123")
    assert not is_flow("https://flow.google.com.example.org/project/123")
    assert not is_flow("https://accounts.google.com/")
    assert not is_flow("https://flow.google.com@other.example/")


@pytest.mark.asyncio
async def test_connector_keeps_local_pairing_token_on_its_bound_origin():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.error import HTTPError

    from app.providers.flow_desktop import MangaForge

    requests = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(302)
            self.send_header("Location", "/outside")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Redirect) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            link = MangaForge(f"http://127.0.0.1:{server.server_port}", "local-test-token")
            with pytest.raises(HTTPError) as err:
                await link.send("/next")
            assert err.value.code == 302
            assert requests == [("/next", "Bearer local-test-token")]
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.asyncio
@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")
async def test_all_clips_joined_locally(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=32x32:r=10:d=0.3", "-c:v", "mpeg4", str(clip)],
        check=True,
    )
    seen = []

    def read(_, key):
        seen.append(key)
        return clip.read_bytes()

    monkeypatch.setattr(flow_video.storage_service, "get_object_bytes", read)
    output = tmp_path / "joined.mp4"

    class Store:
        def fput_object(self, bucket, key, filename, content_type):
            shutil.copyfile(filename, output)

    monkeypatch.setattr(flow_video.storage_service, "get_minio_client", Store)
    monkeypatch.setattr(flow_video.storage_service, "ensure_bucket", lambda *args: None)
    keys = [f"clip-{n}" for n in range(11)]
    await flow_video.export_video(keys, "output.mp4")
    assert seen == keys
    duration = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)]
    )
    assert float(duration) == pytest.approx(3.3, abs=0.05)


@pytest.mark.asyncio
async def test_video_download_supports_seeking(monkeypatch):
    from unittest.mock import MagicMock

    from app.routers.storage import router
    from fastapi import FastAPI

    store = MagicMock()
    store.stat_object.return_value.size = 20
    obj = store.get_object.return_value
    obj.stream.return_value = [b"34567"]
    monkeypatch.setattr(flow_video.storage_service, "get_minio_client", lambda: store)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        res = await http.get("/file/flow/ep/test.mp4", headers={"Range": "bytes=3-7"})
        assert res.status_code == 206 and res.content == b"34567"
        assert res.headers["content-type"] == "video/mp4" and res.headers["content-range"] == "bytes 3-7/20"
        assert store.get_object.call_args.kwargs == {"offset": 3, "length": 5}
        assert obj.close.called and obj.release_conn.called
        assert (await http.get("/file/flow/ep/test.mp4", headers={"Range": "bytes=20-"})).status_code == 416


@pytest.mark.asyncio
async def test_generated_episode_uses_ordered_panels_then_composed_pages():
    from app.models import GeneratedImage, GenerationRun

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        ep = Episode(id="ep", project_id="p", branch_id="b", number=1, source="generated")
        s.add_all([Project(id="p", title="Rain"), Branch(id="b", name="main", project_id="p"), ep])
        s.add(GenerationRun(id="r", episode_id="ep", stage="render"))
        board = {
            "pages": [
                {
                    "page_number": 1,
                    "panels": [
                        {"panel_id": "1-1", "scene": "打开门", "camera": "wide"},
                        {"panel_id": "1-2", "scene": "合上伞", "camera": "close-up"},
                    ],
                }
            ]
        }
        s.add(EpisodeMemory(episode_id=ep.id, type="storyboard_json", content=board))
        db = TestSession(s)
        s.add(GeneratedImage(episode_id="ep", generation_run_id="r", panel_id="1-2", image_path="umbrella"))
        s.commit()
        with pytest.raises(FlowError, match="尚未齐全"):
            await build_plan(db, ep, FlowOptions())
        s.add(GeneratedImage(episode_id="ep", generation_run_id="r", panel_id="1-1", image_path="door"))
        s.commit()
        panel_plan = await build_plan(db, ep, FlowOptions())
        assert panel_plan.shots[0].references == ["door", "umbrella"]
        assert "close-up" in panel_plan.shots[0].prompt
        s.add(
            EpisodeMemory(
                episode_id=ep.id,
                type="layout_result",
                content={"pages": [{"page_number": 1, "image_path": "composed.png"}]},
            )
        )
        s.commit()
        composed = await build_plan(db, ep, FlowOptions())
        assert [r.key for r in composed.sources] == ["composed.png"]
        assert panel_plan.plan_id != composed.plan_id
