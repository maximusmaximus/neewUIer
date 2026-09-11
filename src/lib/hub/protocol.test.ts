import assert from "node:assert/strict";
import { test } from "node:test";
import {
  checksum,
  cctFrame,
  cctHybridFrame,
  hsiFrame,
  parseHex,
  powerFrame,
  powerStatusQuery,
  sceneFrame,
  statusQuery,
  toHex,
} from "./protocol.ts";

test("power on checksum matches known capture", () => {
  assert.equal(toHex(powerFrame(true)), "78 81 01 01 fb");
});

test("power off checksum matches known capture", () => {
  assert.equal(toHex(powerFrame(false)), "78 81 01 02 fc");
});

test("hsi example hue 88 sat 24 bri 100", () => {
  assert.equal(toHex(hsiFrame(88, 24, 100)), "78 86 04 58 00 18 64 d6");
});

test("hsi overflow bit for hue 360", () => {
  const bytes = [...hsiFrame(360, 100, 50)];
  assert.equal(bytes[3], 104);
  assert.equal(bytes[4], 1);
  assert.equal(bytes[bytes.length - 1], checksum(bytes.slice(0, -1)));
});

test("cct 100% 5600K", () => {
  assert.equal(toHex(cctFrame(100, 5600)), "78 87 02 64 38 9d");
});

test("scene cop car", () => {
  assert.equal(toHex(sceneFrame(100, 1)), "78 88 02 64 01 67");
});

test("hybrid CCT encodes green-magenta as offset 50", () => {
  const bytes = [...cctHybridFrame(100, 5600, 0)];
  assert.equal(bytes[2], 0x03);
  assert.equal(bytes[5], 50);
  assert.equal(bytes[bytes.length - 1], checksum(bytes.slice(0, -1)));
});

test("status queries checksum", () => {
  assert.equal(toHex(statusQuery()), "78 84 00 fc");
  assert.equal(toHex(powerStatusQuery()), "78 85 00 fd");
});

test("hex round trip", () => {
  const original = powerFrame(true);
  assert.deepEqual([...parseHex(toHex(original))], [...original]);
});
