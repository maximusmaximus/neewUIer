import assert from "node:assert/strict";
import { test } from "node:test";
import { hsiToRgb, kelvinToRgb, lerpHue } from "./color.ts";

test("red hue is red-dominant", () => {
  const rgb = hsiToRgb(0, 100, 100);
  assert.equal(rgb.r, 255);
  assert.equal(rgb.g, 0);
  assert.equal(rgb.b, 0);
});

test("warm kelvin is warmer than cool", () => {
  const warm = kelvinToRgb(3200);
  const cool = kelvinToRgb(6500);
  assert.ok(warm.r >= cool.r);
  assert.ok(warm.b <= cool.b);
});

test("hue lerp takes the short path", () => {
  const v = lerpHue(350, 10, 0.5);
  assert.ok(v < 20 || v > 340);
});
