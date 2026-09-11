import { clamp } from "./color.ts";
import { SCENES, type HubSettings, type LightPatch, type LightState } from "./types.ts";

export type ParsedBroker = {
  host: string;
  port: number;
  tls: boolean;
  user: string | null;
  password: string | null;
};

const EFFECT_BY_NAME = new Map(
  SCENES.map((scene) => [scene.name.toLowerCase(), scene.id as number]),
);

export function parseBrokerUrl(raw: string): ParsedBroker {
  const value = raw.trim();
  const withScheme = /:\/\//.test(value) ? value : `mqtt://${value}`;
  const url = new URL(withScheme);
  const tls = url.protocol === "mqtts:" || url.protocol === "ssl:" || url.protocol === "tls:";
  return {
    host: url.hostname || "127.0.0.1",
    port: url.port ? Number(url.port) : tls ? 8883 : 1883,
    tls,
    user: url.username ? decodeURIComponent(url.username) : null,
    password: url.password ? decodeURIComponent(url.password) : null,
  };
}

export function rgbToHs(r: number, g: number, b: number): { h: number; s: number } {
  const rr = clamp(r, 0, 255) / 255;
  const gg = clamp(g, 0, 255) / 255;
  const bb = clamp(b, 0, 255) / 255;
  const max = Math.max(rr, gg, bb);
  const min = Math.min(rr, gg, bb);
  const d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === rr) h = ((gg - bb) / d) % 6;
    else if (max === gg) h = (bb - rr) / d + 2;
    else h = (rr - gg) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return { h, s: max === 0 ? 0 : (d / max) * 100 };
}

export function effectToSceneId(effect: string): number | null {
  const raw = effect.trim().toLowerCase();
  if (!raw) return null;
  const named = EFFECT_BY_NAME.get(raw);
  if (named) return named;
  const numeric = raw.match(/^(?:scene\s*)?(\d+)$/);
  if (numeric) {
    const id = Number(numeric[1]);
    return id >= 1 && id <= 17 ? id : null;
  }
  return null;
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return null;
}

function readBrightness(value: unknown): number | null {
  const n = readNumber(value);
  if (n === null) return null;
  if (n <= 100) return clamp(n, 0, 100);
  return clamp((n / 255) * 100, 0, 100);
}

function applyHs(patch: LightPatch, h: number, s: number) {
  patch.hue = ((h % 360) + 360) % 360;
  patch.saturation = clamp(s, 0, 100);
  patch.mode = "hsi";
  patch.power ??= true;
}

/** Accepts Home Assistant JSON light commands and CineNode native patches. */
export function parseHaCommand(body: unknown): LightPatch {
  if (!body || typeof body !== "object") return {};
  const o = body as Record<string, unknown>;
  const patch: LightPatch = {};

  if (typeof o.power === "boolean") patch.power = o.power;
  if (o.mode === "cct" || o.mode === "hsi" || o.mode === "scene") patch.mode = o.mode;
  if (typeof o.connected === "boolean") patch.connected = o.connected;
  for (const key of ["brightness", "kelvin", "gm", "hue", "saturation", "sceneId"] as const) {
    const n = readNumber(o[key]);
    if (n !== null) patch[key] = n;
  }

  if (typeof o.state === "string") {
    const state = o.state.trim().toLowerCase();
    if (state === "on" || state === "true" || state === "1") patch.power = true;
    if (state === "off" || state === "false" || state === "0") patch.power = false;
  }

  const brightness = readBrightness(o.brightness ?? o.brightness_pct);
  if (brightness !== null) {
    patch.brightness = brightness;
    patch.power ??= true;
  }

  const colorMode = typeof o.color_mode === "string" ? o.color_mode.toLowerCase() : "";
  const preferHs = colorMode === "hs" || colorMode === "rgb" || colorMode === "xy";
  const preferCct = colorMode === "color_temp" || colorMode === "colour_temp";

  let kelvin = readNumber(o.color_temp_kelvin);
  const mireds = readNumber(o.color_temp);
  if (kelvin === null && mireds && mireds > 0) kelvin = 1_000_000 / mireds;
  if (kelvin !== null && (preferCct || !preferHs) && patch.mode !== "hsi" && patch.mode !== "scene") {
    patch.kelvin = Math.round(kelvin);
    patch.mode = "cct";
    patch.power ??= true;
  }

  const color = o.color;
  if (color && typeof color === "object") {
    const c = color as Record<string, unknown>;
    const h = readNumber(c.h);
    const s = readNumber(c.s);
    if (h !== null && s !== null && (!preferCct || preferHs)) applyHs(patch, h, s);
    else {
      const r = readNumber(c.r);
      const g = readNumber(c.g);
      const b = readNumber(c.b);
      if (r !== null && g !== null && b !== null && (!preferCct || preferHs)) {
        const hs = rgbToHs(r, g, b);
        applyHs(patch, hs.h, hs.s);
      }
    }
  }

  const hsColor = o.hs_color;
  if (Array.isArray(hsColor) && hsColor.length >= 2 && (!preferCct || preferHs)) {
    const h = readNumber(hsColor[0]);
    const s = readNumber(hsColor[1]);
    if (h !== null && s !== null) applyHs(patch, h, s);
  }

  const rgbColor = o.rgb_color;
  if (Array.isArray(rgbColor) && rgbColor.length >= 3 && (!preferCct || preferHs)) {
    const r = readNumber(rgbColor[0]);
    const g = readNumber(rgbColor[1]);
    const b = readNumber(rgbColor[2]);
    if (r !== null && g !== null && b !== null) {
      const hs = rgbToHs(r, g, b);
      applyHs(patch, hs.h, hs.s);
    }
  }

  if (typeof o.effect === "string") {
    const sceneId = effectToSceneId(o.effect);
    if (sceneId) {
      patch.mode = "scene";
      patch.sceneId = sceneId;
      patch.power ??= true;
    }
  }

  return patch;
}

export function haStatePayload(light: LightState) {
  const on = Boolean(light.connected && light.power);
  const payload: Record<string, unknown> = {
    state: on ? "ON" : "OFF",
    brightness: Math.round(clamp(light.brightness, 0, 100)),
  };
  if (light.mode === "hsi") {
    payload.color_mode = "hs";
    payload.color = { h: Math.round(light.hue), s: Math.round(light.saturation) };
  } else if (light.mode === "scene") {
    payload.color_mode = "hs";
    payload.color = { h: Math.round(light.hue), s: Math.round(light.saturation) };
    const scene = SCENES.find((item) => item.id === light.sceneId);
    payload.effect = scene?.name ?? `Scene ${light.sceneId}`;
  } else {
    payload.color_mode = "color_temp";
    payload.color_temp = Math.round(1_000_000 / Math.max(1, light.kelvin));
    payload.color_temp_kelvin = Math.round(light.kelvin);
  }
  return payload;
}

export function hubLaunchArgs(settings: HubSettings): string[] {
  const args = ["--port", "8787"];
  if (settings.mqttBroker.trim()) args.push("--mqtt", settings.mqttBroker.trim());
  if (settings.mqttUser.trim()) args.push("--mqtt-user", settings.mqttUser.trim());
  if (settings.mqttPassword.trim()) args.push("--mqtt-password", settings.mqttPassword.trim());
  if (settings.mqttDiscoveryPrefix.trim() && settings.mqttDiscoveryPrefix !== "homeassistant") {
    args.push("--discovery-prefix", settings.mqttDiscoveryPrefix.trim());
  }
  return args;
}

export function quoteArg(value: string, windows: boolean): string {
  if (!/[ \t"'&|<>^]/.test(value)) return value;
  if (windows) return `"${value.replace(/"/g, '\\"')}"`;
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

export function formatLaunchCommand(settings: HubSettings, platform: "windows" | "unix"): string {
  const args = hubLaunchArgs(settings).map((part) => quoteArg(part, platform === "windows"));
  if (platform === "windows") return `Start-CineNode.bat ${args.join(" ")}`.trim();
  return `./start-cinenode.sh ${args.join(" ")}`.trim();
}
