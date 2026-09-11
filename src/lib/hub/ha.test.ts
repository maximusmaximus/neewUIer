import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_LIGHTS, DEFAULT_SETTINGS, seedLooks } from "./catalog.ts";
import { entityId, haConfigYaml, mqttDiscovery } from "./ha.ts";

test("entity ids are home assistant safe", () => {
  assert.equal(entityId(DEMO_LIGHTS[0]), "light.cinenode_key");
});

test("mqtt discovery uses json schema and hs+cct when rgb", () => {
  const doc = mqttDiscovery(DEMO_LIGHTS[0], DEFAULT_SETTINGS, "http://studio.local:8787");
  assert.equal(doc.payload.schema, "json");
  assert.deepEqual(doc.payload.supported_color_modes, ["hs", "color_temp"]);
  assert.match(doc.topic, /homeassistant\/light\/cinenode_key\/config/);
});

test("yaml includes rest_command for looks and hub health", () => {
  const yaml = haConfigYaml({
    origin: "http://192.168.1.20:8787",
    settings: DEFAULT_SETTINGS,
    lights: DEMO_LIGHTS,
    looks: seedLooks(),
    patterns: [],
    commands: [],
  });
  assert.match(yaml, /cinenode_look_interview/);
  assert.match(yaml, /resource: http:\/\/192.168.1.20:8787\/api\/health/);
  assert.match(yaml, /cinenode\/<id>\/set/);
});
