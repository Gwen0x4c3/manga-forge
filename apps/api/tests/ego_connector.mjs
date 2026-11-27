// Exercise the shipped Ego script with a synthetic SDK, Google account and MangaForge queue.
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import { syncBuiltinESMExports } from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

test("Ego pins both identities and resumes a paid submission without another click", async t => {
    const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "mangaforge-ego-test-"));
    t.after(() => fs.rm(temporary, { recursive: true, force: true }));
    t.mock.method(os, "homedir", () => temporary);
    syncBuiltinESMExports();
    const endpoint = "https://mangaforge.test/api/v1/flow/browsers/" + randomUUID();
    const project = randomUUID(), runner = randomUUID();
    const image = Buffer.from("89504e470d0a1a0a010203", "hex");
    const digest = createHash("sha256").update(image).digest("hex");
    let job, linked, uploaded, delivered, state, charges = 0, connects = 0;
    let address = "ultra@example.test", accountPanel = false, tileReady = false, location = "about:blank";
    let profiles = [{ id: "Default", name: "Studio Backup" }, { id: "Profile 1", name: "Studio" }];
    const page = {
        label: "p1", url: () => location, goto: url => { location = url; },
        evaluate: (_fn, selector) => {
            if (!selector) return accountPanel ? address : 0;
            if (selector === "flow-grid-tile-container") return { errors: 0, tiles: tileReady ?
                [{ label: "Image", kind: "image", id: "result", ready: true }] : [] };
            if (typeof selector === "string") return false;
            const { role, name } = selector;
            if (["^(Flow )?Agent$", "Clear prompt"].includes(name)) return null;
            return { selector: name, text: "Nano Banana Pro", checked: role === "radio", disabled: false };
        },
        click: selector => {
            if (selector === "Account details") accountPanel = true;
            if (selector === "Close account panel") accountPanel = false;
            if (selector === "Start generation") charges++;
        },
        press() {}, hover() {}, waitForSelector() {}, keyboard: { press() {}, insertText() {} },
        waitForFileChooser: async () => ({ setFiles: async file => { uploaded = await fs.readFile(file); } }),
        waitForEvent: async () => ({ saveAs: async file => fs.writeFile(file, image) })
    };
    const space = { spaceId: 12, page: () => page, pages: () => [page] };
    globalThis.profiles = async () => profiles;
    globalThis.listTaskSpaces = async () => linked ? [linked] : [];
    globalThis.taskSpace = async (id, options) => {
        if (options) {
            assert.equal(options.profileId, "Profile 1");
            linked = { id: 12, ownership: "agent", profileName: "Studio", profileId: "Profile 1" };
        } else assert.equal(id, 12);
        return space;
    };
    globalThis.fetch = async (url, opts) => {
        assert.ok(url.startsWith(endpoint + "/"));
        assert.equal(opts.redirect, "error");
        if (url.endsWith("/connect")) { connects++; return Response.json({ token: "fixture" }); }
        assert.equal(opts.headers.Authorization, "Bearer fixture");
        if (url.endsWith("/inputs/0")) return new Response(image);
        if (url.endsWith("/next")) return Response.json({ job });
        if (url.endsWith("/media")) delivered = opts.body;
        return Response.json({ status: "running" });
    };
    t.mock.method(console, "log", line => { if (line.startsWith("MF_FLOW ")) state = JSON.parse(line.slice(8)).state; });
    let round = 0;
    async function run(mode) {
        state = null;
        globalThis.request = { endpoint, mode, profile: "Studio", expectedProfile: "Studio", runner };
        await import(new URL("../app/providers/flow_ego.mjs?round=" + ++round, import.meta.url));
        return state;
    }
    assert.equal(await run("pair"), "ready");
    profiles.push({ id: "Profile 2", name: "Studio" });
    assert.equal(await run("pair"), "profile_missing");
    assert.equal(connects, 1);
    linked.profileId = "Default";
    assert.equal(await run("probe"), "profile_missing");
    linked.profileId = "Profile 1";
    job = { action: "upload", id: randomUUID(), project, digest };
    assert.equal(await run("tick"), "ready");
    assert.deepEqual(uploaded, image);
    job = { action: "image", id: randomUUID(), project, model: "nano-banana-pro", ratio: "1:1", references: [], prompt: "rain" };
    address = "other@example.test";
    assert.equal(await run("tick"), "account_mismatch");
    job.redelivered = true;
    assert.equal(await run("resume"), "account_mismatch");
    assert.equal(charges, 0);
    address = "ultra@example.test";
    assert.equal(await run("resume"), "ready");
    assert.equal(await run("tick"), "ready");
    assert.equal(charges, 1);
    job.redelivered = true;
    tileReady = true;
    assert.equal(await run("tick"), "ready");
    assert.deepEqual(delivered, image);
    assert.equal(charges, 1);
});
