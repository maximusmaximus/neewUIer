import type { HubSettings, LightState, Look, Pattern, SavedCommand } from "./types.ts";

export function entityId(light: LightState): string {
  const slug = light.id.replace(/[^a-z0-9_]/g, "_");
  return `light.cinenode_${slug}`;
}

export function mqttDiscovery(light: LightState, settings: HubSettings, origin: string) {
  const unique = `cinenode_${light.id}`;
  const prefix = settings.mqttDiscoveryPrefix || "homeassistant";
  return {
    topic: `${prefix}/light/${unique}/config`,
    payload: {
      name: `${settings.studioName} ${light.name}`,
      unique_id: unique,
      schema: "json",
      command_topic: `cinenode/${light.id}/set`,
      state_topic: `cinenode/${light.id}/state`,
      brightness: true,
      brightness_scale: 100,
      color_mode: true,
      supported_color_modes: light.rgb ? ["hs", "color_temp"] : ["color_temp"],
      min_mireds: Math.round(1_000_000 / light.cctRange[1]),
      max_mireds: Math.round(1_000_000 / light.cctRange[0]),
      effect: true,
      effect_list: [
        "Cop Car",
        "Ambulance",
        "Fire Truck",
        "Fireworks",
        "Party",
        "Candlelight",
        "Lightning",
        "Paparazzi",
        "TV Screen",
      ],
      availability_topic: "cinenode/hub/availability",
      payload_available: "online",
      payload_not_available: "offline",
      device: {
        identifiers: ["cinenode_hub"],
        name: `CineNode ${settings.studioName}`,
        manufacturer: "CineNode",
        model: "Local lighting hub",
        sw_version: "1.1.0",
      },
      origin: {
        name: "CineNode",
        sw_version: "1.1.0",
        url: origin,
      },
    },
  };
}

export function restLightYaml(light: LightState, origin: string): string {
  const id = light.id;
  return `  - platform: rest
    name: CineNode ${light.name}
    resource: ${origin}/api/lights/${id}
    method: POST
    headers:
      Content-Type: application/json
    body_on: '{"power": true}'
    body_off: '{"power": false}'
    is_on_template: "{{ value_json.power }}"
    brightness: true
    brightness_template: "{{ value_json.brightness }}"`;
}

export function haConfigYaml(args: {
  origin: string;
  settings: HubSettings;
  lights: LightState[];
  looks: Look[];
  patterns: Pattern[];
  commands: SavedCommand[];
}): string {
  const { origin, settings, lights, looks, patterns, commands } = args;
  const keyHeader = settings.apiKey
    ? `      X-CineNode-Key: "${settings.apiKey}"\n`
    : "";

  const restCommands = [
    ...looks.map(
      (look) => `  cinenode_look_${look.id}:
    url: "${origin}/api/looks/${look.id}/apply"
    method: POST
    headers:
      Content-Type: application/json
${keyHeader}    content: "{}"`,
    ),
    ...patterns.map(
      (pattern) => `  cinenode_pattern_${pattern.id}:
    url: "${origin}/api/patterns/${pattern.id}/start"
    method: POST
    headers:
      Content-Type: application/json
${keyHeader}    content: "{}"`,
    ),
    ...commands.map(
      (command) => `  cinenode_cmd_${command.id}:
    url: "${origin}/api/commands/${command.id}/run"
    method: POST
    headers:
      Content-Type: application/json
${keyHeader}    content: "{}"`,
    ),
    `  cinenode_set_light:
    url: "${origin}/api/lights/{{ light }}"
    method: POST
    headers:
      Content-Type: application/json
${keyHeader}    payload: "{{ payload }}"`,
  ];

  const restLights = lights.map((light) => restLightYaml(light, origin)).join("\n\n");

  return `# CineNode — drop into configuration.yaml
# MQTT discovery is preferred. Point the downloaded hub at the same broker HA uses
# (--mqtt mqtt://homeassistant.local:1883). The hub SUBSCRIBES to cinenode/<id>/set
# so the HA color wheel, kelvin, brightness, and effects move the fixtures live.
# This REST fallback works with nothing but HTTP on your LAN.

rest_command:
${restCommands.join("\n\n")}

rest:
${restLights}

binary_sensor:
  - platform: rest
    name: CineNode Hub
    resource: ${origin}/api/health
    scan_interval: 15
    value_template: "{{ value_json.ok }}"
`;
}

export function haLightState(light: LightState) {
  return {
    entity_id: entityId(light),
    state: !light.connected ? "unavailable" : light.power ? "on" : "off",
    attributes: {
      friendly_name: light.name,
      brightness: Math.round((light.brightness / 100) * 255),
      color_temp: Math.round(1_000_000 / Math.max(1, light.kelvin)),
      hs_color: [Math.round(light.hue), Math.round(light.saturation)],
      color_mode: light.mode === "hsi" ? "hs" : "color_temp",
      effect: light.mode === "scene" ? String(light.sceneId) : null,
      supported_color_modes: light.rgb ? ["hs", "color_temp"] : ["color_temp"],
      connected: light.connected,
      model: light.model,
      mac: light.mac,
    },
  };
}
