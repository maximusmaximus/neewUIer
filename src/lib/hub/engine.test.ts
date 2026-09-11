import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_LIGHTS, seedLooks } from "./catalog.ts";
import { applyLook, applyPatch, mixPatches, opToPatch, targetsOf, tickPattern } from "./engine.ts";
import type { Pattern } from "./types.ts";

test("applyPatch clamps brightness and kelvin", () => {
  const light = applyPatch(DEMO_LIGHTS[0], { brightness: 140, kelvin: 99999 });
  assert.equal(light.brightness, 100);
  assert.equal(light.kelvin, DEMO_LIGHTS[0].cctRange[1]);
});

test("applyLook only touches connected lights present in the look", () => {
  const looks = seedLooks();
  const interview = looks.find((l) => l.id === "interview");
  assert.ok(interview);
  const next = applyLook(DEMO_LIGHTS, interview);
  const key = next.find((l) => l.id === "key");
  assert.equal(key?.kelvin, 3200);
  const accent = next.find((l) => l.id === "accent");
  assert.equal(accent?.connected, false);
});

test("mixPatches lerps brightness", () => {
  const mixed = mixPatches({ brightness: 0 }, { brightness: 100 }, 0.25);
  assert.equal(mixed.brightness, 25);
});

test("tickPattern waits then completes", () => {
  const pattern: Pattern = {
    id: "t",
    name: "t",
    loop: false,
    steps: [
      { id: "a", target: "key", op: { kind: "power", power: true } },
      { id: "b", target: "all", op: { kind: "wait", ms: 200 } },
    ],
  };
  const first = tickPattern(pattern, DEMO_LIGHTS, [], 0, 0, 16);
  assert.equal(first.done, false);
  const second = tickPattern(pattern, first.lights, [], first.stepIndex, first.elapsedInStep, 300);
  assert.equal(second.done, true);
});

test("opToPatch maps command kinds", () => {
  assert.deepEqual(opToPatch({ kind: "power", power: false }), { power: false, brightness: 0 });
  assert.equal(opToPatch({ kind: "wait", ms: 200 }), null);
  assert.equal(opToPatch({ kind: "mix", fromLookId: "a", toLookId: "b", ms: 1 }), null);
  const hsi = opToPatch({ kind: "hsi", hue: 200, saturation: 80, brightness: 40 });
  assert.equal(hsi?.mode, "hsi");
  assert.equal(hsi?.hue, 200);
});

test("tickPattern mix lerps looks on connected lights", () => {
  const looks = seedLooks();
  const pattern: Pattern = {
    id: "m",
    name: "m",
    loop: false,
    steps: [{ id: "a", target: "all", op: { kind: "mix", fromLookId: "night", toLookId: "interview", ms: 100 } }],
  };
  const mid = tickPattern(pattern, DEMO_LIGHTS, looks, 0, 0, 50);
  assert.equal(mid.done, false);
  const key = mid.lights.find((light) => light.id === "key");
  assert.equal(key?.brightness, 62.5);
  const accent = mid.lights.find((light) => light.id === "accent");
  assert.equal(accent?.connected, false);
  assert.equal(accent?.brightness, 0);
});

test("targetsOf filters connected or named lights", () => {
  assert.ok(targetsOf(DEMO_LIGHTS, "all").every((light) => light.connected));
  assert.deepEqual(
    targetsOf(DEMO_LIGHTS, "key").map((light) => light.id),
    ["key"],
  );
});

test("empty pattern is done", () => {
  const result = tickPattern({ id: "e", name: "e", loop: false, steps: [] }, DEMO_LIGHTS, [], 0, 0, 16);
  assert.equal(result.done, true);
});
