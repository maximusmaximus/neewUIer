import { clamp, lerp, lerpHue } from "./color.ts";
import type { CommandOp, LightPatch, LightState, Look, Pattern, PatternStep } from "./types.ts";

export function applyPatch(light: LightState, patch: LightPatch): LightState {
  const next = { ...light, ...patch, lastSeen: Date.now() };
  next.brightness = clamp(next.brightness, 0, 100);
  next.hue = ((next.hue % 360) + 360) % 360;
  next.saturation = clamp(next.saturation, 0, 100);
  next.gm = clamp(next.gm, -50, 50);
  next.kelvin = clamp(next.kelvin, light.cctRange[0], light.cctRange[1]);
  if (patch.power === false) next.brightness = next.brightness;
  return next;
}

export function opToPatch(op: CommandOp): LightPatch | null {
  switch (op.kind) {
    case "power":
      return { power: op.power, brightness: op.power ? undefined : 0 };
    case "cct":
      return {
        power: true,
        mode: "cct",
        kelvin: op.kelvin,
        brightness: op.brightness,
        gm: op.gm ?? 0,
      };
    case "hsi":
      return {
        power: true,
        mode: "hsi",
        hue: op.hue,
        saturation: op.saturation,
        brightness: op.brightness,
      };
    case "scene":
      return { power: true, mode: "scene", sceneId: op.sceneId, brightness: op.brightness };
    case "wait":
    case "mix":
      return null;
  }
}

export function snapshotLook(name: string, lights: LightState[], note = ""): Look {
  const patches: Record<string, LightPatch> = {};
  for (const light of lights) {
    patches[light.id] = {
      power: light.power,
      mode: light.mode,
      brightness: light.brightness,
      kelvin: light.kelvin,
      gm: light.gm,
      hue: light.hue,
      saturation: light.saturation,
      sceneId: light.sceneId,
    };
  }
  return {
    id: `look_${Math.random().toString(36).slice(2, 8)}`,
    name,
    note,
    createdAt: Date.now(),
    patches,
  };
}

export function mixPatches(a: LightPatch, b: LightPatch, t: number): LightPatch {
  const power = (b.power ?? a.power ?? true) ? true : t < 0.5 ? (a.power ?? true) : false;
  const mode = t < 0.5 ? (a.mode ?? "cct") : (b.mode ?? a.mode ?? "cct");
  return {
    power,
    mode,
    brightness: lerp(a.brightness ?? 0, b.brightness ?? 0, t),
    kelvin: lerp(a.kelvin ?? 5600, b.kelvin ?? 5600, t),
    gm: lerp(a.gm ?? 0, b.gm ?? 0, t),
    hue: lerpHue(a.hue ?? 0, b.hue ?? 0, t),
    saturation: lerp(a.saturation ?? 0, b.saturation ?? 0, t),
    sceneId: t < 0.5 ? a.sceneId : b.sceneId,
  };
}

export function applyLook(lights: LightState[], look: Look): LightState[] {
  return lights.map((light) => {
    const patch = look.patches[light.id];
    if (!patch) return light;
    if (!light.connected) return light;
    return applyPatch(light, patch);
  });
}

export type TickResult = {
  lights: LightState[];
  stepIndex: number;
  elapsedInStep: number;
  done: boolean;
};

export function stepDuration(step: PatternStep): number {
  if (step.op.kind === "wait") return Math.max(0, step.op.ms);
  if (step.op.kind === "mix") return Math.max(0, step.op.ms);
  return 0;
}

export function tickPattern(
  pattern: Pattern,
  lights: LightState[],
  looks: Look[],
  stepIndex: number,
  elapsedInStep: number,
  dt: number,
): TickResult {
  if (pattern.steps.length === 0) {
    return { lights, stepIndex: 0, elapsedInStep: 0, done: true };
  }

  let idx = stepIndex;
  let elapsed = elapsedInStep + dt;
  let current = lights;
  let guard = 0;

  while (guard++ < 32) {
    const step = pattern.steps[idx];
    if (!step) {
      if (pattern.loop) {
        idx = 0;
        elapsed = 0;
        continue;
      }
      return { lights: current, stepIndex: idx, elapsedInStep: 0, done: true };
    }

    const op = step.op;
    const duration = stepDuration(step);

    if (op.kind === "mix") {
      const from = looks.find((l) => l.id === op.fromLookId);
      const to = looks.find((l) => l.id === op.toLookId);
      const t = duration === 0 ? 1 : clamp(elapsed / duration, 0, 1);
      if (from && to) {
        current = current.map((light) => {
          if (!light.connected) return light;
          const a = from.patches[light.id] ?? {};
          const b = to.patches[light.id] ?? {};
          return applyPatch(light, mixPatches(a, b, t));
        });
      }
      if (elapsed < duration) {
        return { lights: current, stepIndex: idx, elapsedInStep: elapsed, done: false };
      }
      idx += 1;
      elapsed -= duration;
      continue;
    }

    if (op.kind === "wait") {
      if (elapsed < duration) {
        return { lights: current, stepIndex: idx, elapsedInStep: elapsed, done: false };
      }
      idx += 1;
      elapsed -= duration;
      continue;
    }

    const patch = opToPatch(op);
    if (patch) {
      current = current.map((light) => {
        if (!light.connected) return light;
        if (step.target !== "all" && light.id !== step.target) return light;
        return applyPatch(light, patch);
      });
    }
    idx += 1;
    elapsed = 0;
  }

  return { lights: current, stepIndex: idx, elapsedInStep: elapsed, done: !pattern.loop };
}

export function targetsOf(lights: LightState[], target: "all" | string): LightState[] {
  if (target === "all") return lights.filter((l) => l.connected);
  return lights.filter((l) => l.id === target);
}
