export type HubPlatform = "windows" | "macos" | "linux";

export const HUB_PACKS: {
  id: HubPlatform;
  title: string;
  file: string;
  href: string;
  blurb: string;
  run: string;
  note: string;
}[] = [
  {
    id: "windows",
    title: "Windows",
    file: "cinenode-windows.zip",
    href: "/downloads/cinenode-windows.zip",
    blurb: "Double-click Start-CineNode.bat. Uses the PC Bluetooth radio — not WSL.",
    run: "Start-CineNode.bat",
    note: "Python 3.10+ on PATH, or the launcher will offer winget. Close the Neewer app first.",
  },
  {
    id: "macos",
    title: "macOS",
    file: "cinenode-macos.zip",
    href: "/downloads/cinenode-macos.zip",
    blurb: "Unzip, then run start-cinenode.sh. Allow Bluetooth when macOS asks.",
    run: "./start-cinenode.sh",
    note: "Needs Python 3 from python.org or Homebrew. Keep the Neewer app closed.",
  },
  {
    id: "linux",
    title: "Linux",
    file: "cinenode-linux.zip",
    href: "/downloads/cinenode-linux.zip",
    blurb: "BlueZ + a Bluetooth adapter. Same script Home Assistant OS users can run on a Pi.",
    run: "./start-cinenode.sh",
    note: "Install bluez. Add your user to the bluetooth group if scan fails.",
  },
];

export function detectPlatform(): HubPlatform {
  if (typeof navigator === "undefined") return "linux";
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua)) return "macos";
  return "linux";
}
