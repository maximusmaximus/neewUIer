import assert from "node:assert/strict";
import { test } from "node:test";
import { GITHUB_OWNER, GITHUB_REPO, GITHUB_URL } from "./github.ts";

test("public repo coordinates are stable", () => {
  assert.equal(GITHUB_OWNER, "maximusmaximus");
  assert.equal(GITHUB_REPO, "neewUIer");
  assert.equal(GITHUB_URL, "https://github.com/maximusmaximus/neewUIer");
});
