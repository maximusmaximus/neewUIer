/** Neewer BLE packet builders. Checksum is the low 8 bits of the sum. */

export const NEEWER_SERVICE = "69400001-b5a3-f393-e0a9-e50e24dcca99";
export const NEEWER_WRITE = "69400002-b5a3-f393-e0a9-e50e24dcca99";
export const NEEWER_NOTIFY = "69400003-b5a3-f393-e0a9-e50e24dcca99";

export function checksum(bytes: number[]): number {
  return bytes.reduce((a, b) => a + b, 0) & 0xff;
}

export function frame(bytes: number[]): Uint8Array {
  return Uint8Array.from([...bytes, checksum(bytes)]);
}

export function powerFrame(on: boolean): Uint8Array {
  return frame([0x78, 0x81, 0x01, on ? 0x01 : 0x02]);
}

export function hsiFrame(hue: number, sat: number, bri: number): Uint8Array {
  const h = Math.max(0, Math.min(360, Math.round(hue)));
  const hueLo = h <= 255 ? h : h - 256;
  const hueHi = h <= 255 ? 0 : 1;
  const s = Math.max(0, Math.min(100, Math.round(sat)));
  const b = Math.max(0, Math.min(100, Math.round(bri)));
  return frame([0x78, 0x86, 0x04, hueLo, hueHi, s, b]);
}

export function cctFrame(bri: number, kelvin: number): Uint8Array {
  const b = Math.max(0, Math.min(100, Math.round(bri)));
  const t = Math.max(0, Math.min(255, Math.round(kelvin / 100)));
  return frame([0x78, 0x87, 0x02, b, t]);
}

export function cctHybridFrame(bri: number, kelvin: number, gm: number): Uint8Array {
  const b = Math.max(0, Math.min(100, Math.round(bri)));
  const t = Math.max(0, Math.min(255, Math.round(kelvin / 100)));
  const g = Math.max(0, Math.min(100, Math.round(gm + 50)));
  return frame([0x78, 0x87, 0x03, b, t, g]);
}

export function sceneFrame(bri: number, sceneId: number): Uint8Array {
  const b = Math.max(0, Math.min(100, Math.round(bri)));
  const s = Math.max(1, Math.min(17, Math.round(sceneId)));
  return frame([0x78, 0x88, 0x02, b, s]);
}

export function statusQuery(): Uint8Array {
  return frame([0x78, 0x84, 0x00]);
}

export function powerStatusQuery(): Uint8Array {
  return frame([0x78, 0x85, 0x00]);
}

export function toHex(bytes: Uint8Array): string {
  return [...bytes].map((n) => n.toString(16).padStart(2, "0")).join(" ");
}

export function parseHex(hex: string): Uint8Array {
  const parts = hex.trim().split(/\s+/).filter(Boolean);
  return Uint8Array.from(parts.map((p) => parseInt(p, 16)));
}
