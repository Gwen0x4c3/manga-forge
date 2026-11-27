"""Run MangaForge's Flow connector using the native Ego Lite CLI, locally or over Ego Bridge."""

import argparse
import fcntl
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "apps/api/app/providers"
sys.path.insert(0, str(PROVIDERS))
from flow_desktop import DATA, FlowBrowserError, atomic_write, parse_pair  # noqa: E402


def invoke(executable, script, request):
    # Use stdin throughout. The short-lived pairing code must never appear in argv or service logs.
    result = subprocess.run(
        [executable, "nodejs"],
        input="const request = " + json.dumps(request) + ";\n" + script,
        capture_output=True,
        text=True,
        env={**os.environ, "EGO_BRIDGE_HINTS": "0"},
    )
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        if line.startswith("MF_FLOW "):
            return json.loads(line[len("MF_FLOW ") :])
    # A lost reply can outlive the Linux subprocess. Wait for the remote round before checking the page.
    receipt = re.search(r"(?:requestId=|bridge result )([0-9a-f]{32})\b", result.stderr)
    if receipt:
        while True:
            check = subprocess.run(
                [executable, "bridge", "result", receipt[1]],
                capture_output=True,
                text=True,
            )
            try:
                if json.loads(check.stdout).get("status") != "running":
                    break
            except ValueError:
                break
            time.sleep(5)
    # The native CLI may include script source in diagnostics. Never echo it.
    return {"state": "unavailable"}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument(
        "--pair", action="store_true", help="pair with the code from MangaForge Models"
    )
    args.add_argument(
        "--profile", help="exact Ego Lite profile name or ID to bind during pairing"
    )
    args.add_argument(
        "--setup-only",
        action="store_true",
        help="pair and verify the connection, then exit",
    )
    args.add_argument(
        "--resume",
        action="store_true",
        help="return control of the dedicated Flow tab after login",
    )
    opts = args.parse_args()
    cli = shutil.which("ego-browser")
    if not cli:
        sys.exit(
            "找不到 ego-browser。请在已连接 Ego Bridge 的 Linux 主机或安装 Ego Lite 的 Mac 上运行。"
        )
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = DATA / "ego-endpoint.json"
    script = (PROVIDERS / "flow_ego.mjs").read_text()
    runner = str(uuid.uuid4())
    existing = json.loads(config.read_text()) if config.exists() else {}
    switch_profile = opts.profile is not None and opts.profile != existing.get(
        "profile"
    )
    if opts.pair or not existing or switch_profile:
        prompt = "粘贴模型中心的完整配对串（输入隐藏）："
        code_input = (
            getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline()
        )
        endpoint, code = parse_pair(code_input)
        profile = opts.profile if opts.profile is not None else existing.get("profile")
        result = invoke(
            cli,
            script,
            {
                "mode": "pair",
                "endpoint": endpoint,
                "code": code,
                "runner": runner,
                "profile": profile,
            },
        )
        if result["state"] == "profile_missing":
            sys.exit(
                "没有找到唯一匹配的 Ego profile。请使用完整名称或浏览器 profile ID。"
            )
        if result["state"] not in {"ready", "login", "paused", "paired"}:
            sys.exit(
                "配对未完成。请确认 Ego Bridge 在线、Mac 可打开配对串中的 MangaForge 地址，且配对串有效。"
            )
        atomic_write(
            config, json.dumps({"endpoint": endpoint, "profile": profile}).encode()
        )
        print("Ego Lite 已配对。", flush=True)
    else:
        endpoint = existing["endpoint"]
    profile = opts.profile if opts.profile is not None else existing.get("profile")
    request = {
        "endpoint": endpoint,
        "runner": runner,
        "mode": "resume" if opts.resume else "probe",
        "expectedProfile": profile,
    }
    if opts.resume or opts.setup_only:
        state = invoke(cli, script, request)["state"]
        print(describe(state), flush=True)
        return 0 if state in {"ready", "login", "paused"} else 1
    with (DATA / "ego-runner.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Ego 连接器已经在运行。")
        last = None
        probe_first = False
        while True:
            result = invoke(
                cli, script, {**request, "mode": "probe" if probe_first else "tick"}
            )
            state = result["state"]
            if last != state:
                print(describe(state), flush=True)
            if state == "unauthorized":
                return 0  # A replacement connector or revoked credential intentionally ends this service.
            if state == "unavailable" and not probe_first:
                request["runner"] = str(
                    uuid.uuid4()
                )  # Let the previous job lease expire after a lost reply.
            probe_first = state == "unavailable"
            last = state
            time.sleep(2 if state == "ready" else 10)


def describe(state):
    return {
        "ready": "Ego Lite 已登录 Google Flow，可接收任务。",
        "login": "请在 Mac 的专用 Ego 标签页登录 Flow，然后运行 make flow-ego-resume。",
        "paused": "Ego 工作区已交给用户或已关闭。准备好后运行 make flow-ego-resume。",
        "profile_missing": "Ego 工作区与已绑定的 profile 不一致，已暂停。请检查指定的 Mac profile。",
        "account_mismatch": "Flow 账号与绑定记录不符或无法核对。切回绑定账号后运行 make flow-ego-resume。",
        "unauthorized": "MangaForge 配对已失效，请重新生成配对串并以 --pair 运行。",
    }.get(state, "Ego 或 MangaForge 暂不可达，请检查 Mac、Ego Bridge 和服务地址。")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FlowBrowserError as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        pass
