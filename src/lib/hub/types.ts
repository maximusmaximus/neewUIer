export type LightMode = "cct" | "hsi" | "scene";

export type LightState = {
  id: string;
  name: string;
  model: string;
  modelCode: string;
  mac: string;
  connected: boolean;
  power: boolean;
  mode: LightMode;
  brightness: number;
  kelvin: number;
  gm: number;
  hue: number;
  saturation: number;
  sceneId: number;
  lastSeen: number;
  rssi: number | null;
  rgb: boolean;
  cctRange: [number, number];
  lightType: 0 | 1 | 2;
  cctOnly: boolean;
};

export type LightPatch = Partial<
  Pick<
    LightState,
    | "power"
    | "mode"
    | "brightness"
    | "kelvin"
    | "gm"
    | "hue"
    | "saturation"
    | "sceneId"
    | "connected"
  >
>;

export type CommandOp =
  | { kind: "power"; power: boolean }
  | { kind: "cct"; kelvin: number; brightness: number; gm?: number }
  | { kind: "hsi"; hue: number; saturation: number; brightness: number }
  | { kind: "scene"; sceneId: number; brightness: number }
  | { kind: "wait"; ms: number }
  | { kind: "mix"; fromLookId: string; toLookId: string; ms: number };

export type SavedCommand = {
  id: string;
  name: string;
  target: "all" | string;
  op: CommandOp;
};

export type Look = {
  id: string;
  name: string;
  note: string;
  createdAt: number;
  patches: Record<string, LightPatch>;
};

export type PatternStep = {
  id: string;
  target: "all" | string;
  op: CommandOp;
};

export type Pattern = {
  id: string;
  name: string;
  loop: boolean;
  steps: PatternStep[];
};

export type HubSettings = {
  studioName: string;
  hubUrl: string;
  useLanHub: boolean;
  apiKey: string;
  mqttBroker: string;
  mqttDiscoveryPrefix: string;
  mqttUser: string;
  mqttPassword: string;
  haBaseUrl: string;
};

export type HubSnapshot = {
  revision: number;
  lights: LightState[];
  looks: Look[];
  patterns: Pattern[];
  commands: SavedCommand[];
  settings: HubSettings;
};

export const SCENES = [
  { id: 1, name: "Cop Car" },
  { id: 2, name: "Ambulance" },
  { id: 3, name: "Fire Truck" },
  { id: 4, name: "Fireworks" },
  { id: 5, name: "Party" },
  { id: 6, name: "Candlelight" },
  { id: 7, name: "Lightning" },
  { id: 8, name: "Paparazzi" },
  { id: 9, name: "TV Screen" },
] as const;
