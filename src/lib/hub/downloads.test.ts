import assert from "node:assert/strict";
import { test } from "node:test";
import { detectPlatform, HUB_PACKS } from "./downloads.ts";

test("each OS pack has a zip download path", () => {
  const ids = HUB_PACKS.map((pack) => pack.id).sort();
  assert.deepEqual(ids, ["linux", "macos", "windows"]);
  for (const pack of HUB_PACKS) {
    assert.match(pack.href, /^\/downloads\/cinenode-\w+\.zip$/);
    assert.match(pack.file, /^cinenode-/);
    assert.ok(pack.blurb.length > 20);
  }
});

test("detectPlatform falls back off browser", () => {
  assert.equal(detectPlatform(), "linux");
});
