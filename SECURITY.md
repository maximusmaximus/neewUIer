# Security

This hub talks to lights on **your LAN**. It is not a cloud service.

## Report a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/maximusmaximus/neewUIer/security/advisories/new) rather than a public issue.

Include:

- Affected version / commit
- What an attacker on the LAN could do
- A minimal reproduction (no radio dump required)

Do not open a public issue for credential leaks, MQTT auth bypasses, or unauthenticated LAN control surprises.

## What this project does not promise

- The REST API is intentionally open on the LAN (that is the product: any device on the network can light the rig). Put it behind a trusted network or add `apiKey` at the studio if you need a lock.
- BLE frames are reverse-engineered. We will not merge firmware exploits or pairing bypasses.
