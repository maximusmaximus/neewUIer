import assert from "node:assert/strict";
import { test } from "node:test";
import { clamp, hsiToRgb, kelvinToRgb, lerp, lerpHue, mixRgb, rgbCss } from "./color.ts";

test("red hue is red-dominant", () => {
  const rgb = hsiToRgb(0, 100, 100);
  assert.equal(rgb.r, 255);
  assert.equal(rgb.g, 0);
  assert.equal(rgb.b, 0);
});

test("cyan hue is green+blue", () => {
  const rgb = hsiToRgb(180, 100, 100);
  assert.equal(rgb.r, 0);
  assert.equal(rgb.g, 255);
  assert.equal(rgb.b, 255);
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

test("clamp lerp and css helpers", () => {
  assert.equal(clamp(120, 0, 100), 100);
  assert.equal(lerp(0, 10, 0.5), 5);
  assert.equal(rgbCss({ r: 1, g: 2, b: 3 }, 0.5), "rgb(1 2 3 / 0.5)");
  assert.deepEqual(mixRgb({ r: 0, g: 0, b: 0 }, { r: 10, g: 0, b: 0 }, 0.5), { r: 5, g: 0, b: 0 });
});
