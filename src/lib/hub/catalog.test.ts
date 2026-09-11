import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_LIGHTS, DEFAULT_SETTINGS, seedCommands, seedLooks, seedPatterns } from "./catalog.ts";

test("demo rig has unique ids and a disconnected accent", () => {
  const ids = DEMO_LIGHTS.map((light) => light.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.includes("key"));
  const accent = DEMO_LIGHTS.find((light) => light.id === "accent");
  assert.equal(accent?.connected, false);
  const hair = DEMO_LIGHTS.find((light) => light.id === "hair");
  assert.equal(hair?.cctOnly, true);
  assert.equal(hair?.rgb, false);
});

test("default settings point at Home Assistant MQTT", () => {
  assert.equal(DEFAULT_SETTINGS.useLanHub, false);
  assert.match(DEFAULT_SETTINGS.mqttBroker, /^mqtt:\/\//);
  assert.equal(DEFAULT_SETTINGS.mqttDiscoveryPrefix, "homeassistant");
});

test("seed looks cover the named rig", () => {
  const looks = seedLooks();
  const interview = looks.find((look) => look.id === "interview");
  assert.ok(interview);
  assert.equal(interview.patches.key?.kelvin, 3200);
  assert.equal(interview.patches.tube?.power, false);
});

test("seed commands and patterns are runnable", () => {
  const commands = seedCommands();
  assert.ok(commands.some((command) => command.op.kind === "power" && command.target === "all"));
  const patterns = seedPatterns();
  assert.ok(patterns.some((pattern) => pattern.loop));
  assert.ok(patterns[0].steps.length > 0);
});
