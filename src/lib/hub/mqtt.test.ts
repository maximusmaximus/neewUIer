import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { DEMO_LIGHTS, DEFAULT_SETTINGS } from "./catalog.ts";
import {
  effectToSceneId,
  formatLaunchCommand,
  haStatePayload,
  parseBrokerUrl,
  parseHaCommand,
  rgbToHs,
} from "./mqtt.ts";

test("parses HA JSON hs color wheel command", () => {
  const patch = parseHaCommand({
    state: "ON",
    brightness: 80,
    color_mode: "hs",
    color: { h: 210, s: 70 },
  });
  assert.equal(patch.power, true);
  assert.equal(patch.mode, "hsi");
  assert.equal(patch.hue, 210);
  assert.equal(patch.saturation, 70);
  assert.equal(patch.brightness, 80);
});

test("parses HA color_temp mireds into kelvin", () => {
  const patch = parseHaCommand({ state: "ON", color_temp: 153 });
  assert.equal(patch.mode, "cct");
  assert.equal(patch.kelvin, Math.round(1_000_000 / 153));
  assert.equal(patch.power, true);
});

test("parses color_temp_kelvin", () => {
  const patch = parseHaCommand({ state: "ON", color_temp_kelvin: 5600, brightness: 40 });
  assert.equal(patch.mode, "cct");
  assert.equal(patch.kelvin, 5600);
  assert.equal(patch.brightness, 40);
});

test("scales brightness from 255 when over 100", () => {
  const patch = parseHaCommand({ brightness: 204 });
  assert.equal(patch.brightness, 80);
});

test("maps HA effect names onto Neewer scenes", () => {
  assert.equal(effectToSceneId("Party"), 5);
  const patch = parseHaCommand({ state: "ON", effect: "Candlelight" });
  assert.equal(patch.mode, "scene");
  assert.equal(patch.sceneId, 6);
});

test("accepts native CineNode patches alongside HA fields", () => {
  const patch = parseHaCommand({ power: true, mode: "hsi", hue: 32, saturation: 12, brightness: 50 });
  assert.deepEqual(patch, {
    power: true,
    mode: "hsi",
    hue: 32,
    saturation: 12,
    brightness: 50,
  });
});

test("OFF does not force a color mode", () => {
  const patch = parseHaCommand({ state: "OFF" });
  assert.equal(patch.power, false);
  assert.equal(patch.mode, undefined);
});

test("rgb_color converts to hs", () => {
  const hs = rgbToHs(255, 0, 0);
  assert.ok(hs.h < 1 || hs.h > 359);
  assert.ok(hs.s > 99);
  const patch = parseHaCommand({ rgb_color: [0, 255, 0], state: "ON" });
  assert.equal(patch.mode, "hsi");
  assert.ok((patch.hue ?? 0) > 100 && (patch.hue ?? 0) < 140);
});

test("state payload uses brightness_scale 100", () => {
  const payload = haStatePayload(DEMO_LIGHTS[0]);
  assert.equal(payload.state, "ON");
  assert.equal(payload.brightness, 72);
  assert.equal(payload.color_mode, "color_temp");
});

test("broker url parser reads user and tls port", () => {
  const parsed = parseBrokerUrl("mqtts://user:secret@ha.local:8883");
  assert.equal(parsed.host, "ha.local");
  assert.equal(parsed.port, 8883);
  assert.equal(parsed.tls, true);
  assert.equal(parsed.user, "user");
  assert.equal(parsed.password, "secret");
});

test("windows launch command quotes mqtt password", () => {
  const cmd = formatLaunchCommand(
    { ...DEFAULT_SETTINGS, mqttPassword: "a b" },
    "windows",
  );
  assert.match(cmd, /Start-CineNode\.bat/);
  assert.match(cmd, /--mqtt-password "a b"/);
});

test("python and typescript share HA command fixtures", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "../../../hub/tests/fixtures/ha-commands.json");
  const cases = JSON.parse(readFileSync(root, "utf8")) as Array<{
    name: string;
    in: Record<string, unknown>;
    out: Record<string, unknown>;
  }>;
  assert.ok(cases.length >= 8);
  for (const item of cases) {
    const got = parseHaCommand(item.in) as Record<string, unknown>;
    for (const [key, value] of Object.entries(item.out)) {
      if (typeof value === "number" && typeof got[key] === "number") {
        assert.ok(Math.abs(Number(got[key]) - value) <= 1, `${item.name} ${key}`);
      } else {
        assert.equal(got[key], value, `${item.name} ${key}`);
      }
    }
    if (item.name === "OFF does not force mode") assert.equal(got.mode, undefined);
  }
});
