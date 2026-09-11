import type { HubSettings, LightState, Look, Pattern, SavedCommand } from "./types.ts";

const now = () => Date.now();

function light(partial: Omit<LightState, "lastSeen" | "rssi"> & { rssi?: number | null }): LightState {
  return {
    ...partial,
    rssi: partial.rssi ?? (partial.connected ? -48 : null),
    lastSeen: now(),
  };
}

export const DEMO_LIGHTS: LightState[] = [
  light({
    id: "key",
    name: "Key",
    model: "RGB660 PRO",
    modelCode: "RGB660PRO",
    mac: "D2:E2:75:8B:36:45",
    connected: true,
    power: true,
    mode: "cct",
    brightness: 72,
    kelvin: 5600,
    gm: 0,
    hue: 32,
    saturation: 0,
    sceneId: 1,
    rgb: true,
    cctRange: [3200, 5600],
    lightType: 0,
    cctOnly: false,
  }),
  light({
    id: "fill",
    name: "Fill",
    model: "RGB176",
    modelCode: "RGB176",
    mac: "F8:46:85:EF:47:70",
    connected: true,
    power: true,
    mode: "hsi",
    brightness: 38,
    kelvin: 4300,
    gm: 0,
    hue: 28,
    saturation: 42,
    sceneId: 6,
    rgb: true,
    cctRange: [3200, 5600],
    lightType: 0,
    cctOnly: false,
    rssi: -61,
  }),
  light({
    id: "hair",
    name: "Hair",
    model: "GL1 Pro",
    modelCode: "20220001",
    mac: "A4:C1:38:11:90:22",
    connected: true,
    power: true,
    mode: "cct",
    brightness: 44,
    kelvin: 3200,
    gm: -8,
    hue: 30,
    saturation: 0,
    sceneId: 1,
    rgb: false,
    cctRange: [2900, 7000],
    lightType: 1,
    cctOnly: true,
    rssi: -55,
  }),
  light({
    id: "tube",
    name: "Tube",
    model: "TL60 RGB",
    modelCode: "TL60",
    mac: "C3:1A:09:77:12:AB",
    connected: true,
    power: false,
    mode: "hsi",
    brightness: 0,
    kelvin: 5600,
    gm: 0,
    hue: 210,
    saturation: 80,
    sceneId: 5,
    rgb: true,
    cctRange: [3200, 5600],
    lightType: 0,
    cctOnly: false,
    rssi: -70,
  }),
  light({
    id: "accent",
    name: "Accent",
    model: "MS60C",
    modelCode: "20230080",
    mac: "E1:90:44:08:CC:19",
    connected: false,
    power: false,
    mode: "cct",
    brightness: 0,
    kelvin: 5600,
    gm: 0,
    hue: 0,
    saturation: 0,
    sceneId: 1,
    rgb: true,
    cctRange: [2700, 6500],
    lightType: 1,
    cctOnly: false,
    rssi: null,
  }),
];

export const DEFAULT_SETTINGS: HubSettings = {
  studioName: "Stage A",
  hubUrl: "",
  useLanHub: false,
  apiKey: "",
  mqttBroker: "mqtt://homeassistant.local:1883",
  mqttDiscoveryPrefix: "homeassistant",
  mqttUser: "",
  mqttPassword: "",
  haBaseUrl: "",
};

export function seedLooks(): Look[] {
  return [
    {
      id: "interview",
      name: "Interview Warm",
      note: "Key 3200K, fill low, hair rim.",
      createdAt: now(),
      patches: {
        key: { power: true, mode: "cct", kelvin: 3200, brightness: 70, gm: -4 },
        fill: { power: true, mode: "cct", kelvin: 3400, brightness: 28 },
        hair: { power: true, mode: "cct", kelvin: 4300, brightness: 36 },
        tube: { power: false, brightness: 0 },
      },
    },
    {
      id: "daylight",
      name: "Daylight Desk",
      note: "5600K across the rig.",
      createdAt: now(),
      patches: {
        key: { power: true, mode: "cct", kelvin: 5600, brightness: 80 },
        fill: { power: true, mode: "cct", kelvin: 5600, brightness: 45 },
        hair: { power: true, mode: "cct", kelvin: 5600, brightness: 30 },
        tube: { power: false },
      },
    },
    {
      id: "night",
      name: "Night Exterior",
      note: "Cool key, cyan edge.",
      createdAt: now(),
      patches: {
        key: { power: true, mode: "cct", kelvin: 5600, brightness: 55 },
        fill: { power: true, mode: "hsi", hue: 210, saturation: 55, brightness: 22 },
        hair: { power: true, mode: "cct", kelvin: 6500, brightness: 18 },
        tube: { power: true, mode: "hsi", hue: 198, saturation: 70, brightness: 40 },
      },
    },
  ];
}

export function seedCommands(): SavedCommand[] {
  return [
    {
      id: "all-on",
      name: "All on",
      target: "all",
      op: { kind: "power", power: true },
    },
    {
      id: "all-off",
      name: "All off",
      target: "all",
      op: { kind: "power", power: false },
    },
    {
      id: "cop",
      name: "Cop car",
      target: "all",
      op: { kind: "scene", sceneId: 1, brightness: 80 },
    },
    {
      id: "candle",
      name: "Candle fill",
      target: "fill",
      op: { kind: "scene", sceneId: 6, brightness: 40 },
    },
  ];
}

export function seedPatterns(): Pattern[] {
  return [
    {
      id: "open",
      name: "Open the room",
      loop: false,
      steps: [
        { id: "s1", target: "all", op: { kind: "power", power: true } },
        { id: "s2", target: "all", op: { kind: "wait", ms: 400 } },
        {
          id: "s3",
          target: "all",
          op: { kind: "mix", fromLookId: "night", toLookId: "interview", ms: 2400 },
        },
      ],
    },
    {
      id: "party-mix",
      name: "Party chase",
      loop: true,
      steps: [
        { id: "p1", target: "tube", op: { kind: "hsi", hue: 0, saturation: 90, brightness: 70 } },
        { id: "p2", target: "all", op: { kind: "wait", ms: 500 } },
        { id: "p3", target: "fill", op: { kind: "hsi", hue: 280, saturation: 80, brightness: 50 } },
        { id: "p4", target: "all", op: { kind: "wait", ms: 500 } },
        { id: "p5", target: "tube", op: { kind: "hsi", hue: 200, saturation: 90, brightness: 70 } },
        { id: "p6", target: "all", op: { kind: "wait", ms: 500 } },
      ],
    },
  ];
}
