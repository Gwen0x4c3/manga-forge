import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

test("Flow commands work on the selected page without a Google account menu", async () => {
    const script = await readFile(new URL("../app/flow_extension/flow.js", import.meta.url), "utf8");
    const window = {};
    window.top = window;
    let listener;
    let submits = 0;
    const button = {
        getClientRects: () => [{}],
        cloneNode: () => ({ textContent: "Start generation", querySelectorAll: () => [] }),
        getAttribute: () => null,
        click: () => { submits++; },
    };
    const prompt = { textContent: "Animate this panel", querySelectorAll: () => [] };
    const document = {
        getElementById: () => null,
        querySelector: () => ({ cloneNode: () => prompt }),
        querySelectorAll(selector) {
            if (selector.includes("Ingredient")) return [];
            assert.equal(selector, '[role="button"],button');
            return [button];
        },
    };
    const context = {
        window, document, getComputedStyle: () => ({ visibility: "visible" }),
        chrome: { runtime: { id: "fixture", getManifest: () => ({ version: "fixture" }), onMessage: { addListener: fn => { listener = fn; } } } },
    };
    vm.runInNewContext(script, context);
    const send = (op, args) => new Promise(resolve => {
        listener({ channel: context.__mangaForgeFlowLoaded, op, ...args }, { id: "fixture" }, resolve);
    });

    assert.equal((await send("probe")).value, true);
    const submit = () => send("submit", { prompt: prompt.textContent, referenceCount: 0 });
    assert.equal((await submit()).ok, true);
    // Only the actual prompt and references gate submission.
    const changed = await send("submit", { prompt: "A different shot", referenceCount: 0 });
    assert.equal(changed.kind, "unsubmitted");
    assert.equal(submits, 1);
});

test("upload waits for the Flow rights dialog and respects agreement, dismissal and a fresh retry", async () => {
    const script = await readFile(new URL("../app/flow_extension/flow.js", import.meta.url), "utf8");
    let listener, onClick, open = true, hasTile = false, hasMedia = false;
    const name = "mf-" + "a".repeat(64) + ".png";
    const button = (label) => ({
        getClientRects: () => [{}], getAttribute: () => null,
        cloneNode: () => ({ textContent: label, querySelectorAll: () => [] }),
        click: () => assert.fail("The extension clicked the consent dialog"),
    });
    const agree = button("I agree"), cancel = button("Cancel");
    const dialog = {
        getClientRects: () => [{}], getAttribute: () => null,
        querySelector: () => ({ textContent: "Rights to use this image" }),
        querySelectorAll: () => [cancel, agree],
        addEventListener: (_, fn) => { onClick = fn; },
    };
    const tile = {
        getAttribute: () => name, get innerText() { return hasMedia ? "" : "48%"; },
        querySelector: selector => hasMedia && selector === "[data-media-id]" ? { getAttribute: () => "real-media" } : null,
    };
    const document = {
        getElementById: () => null,
        querySelectorAll: selector => selector.includes("dialog") ? (open ? [dialog] : []) : (hasTile ? [tile] : []),
    };
    const window = {}; window.top = window;
    const context = { window, document, performance: { timeOrigin: 100 }, getComputedStyle: () => ({ visibility: "visible" }),
        chrome: { runtime: { id: "fixture", getManifest: () => ({ version: "test" }), onMessage: { addListener: fn => { listener = fn; } } } } };
    vm.runInNewContext(script, context);
    async function state(attempt) {
        const message = { channel: context.__mangaForgeFlowLoaded, op: "uploadState", name, attempt };
        const result = await new Promise(resolve => listener(message, { id: "fixture" }, resolve));
        assert.equal(result.ok, true);
        return result.value.state;
    }
    assert.equal(await state("first"), "rights");
    onClick({ target: { closest: () => cancel } });
    open = false;
    assert.equal(await state("first"), "cancelled");
    assert.equal(await state("retry"), "pending");
    open = true;
    assert.equal(await state("retry"), "rights");
    onClick({ target: { closest: () => agree } });
    open = false;
    assert.equal(await state("retry"), "pending");
    hasTile = true;
    assert.equal(await state("retry"), "transferring");
    hasMedia = true;
    assert.equal(await state("retry"), "uploaded");
});
