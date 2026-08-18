# NexaCrew — AI-Native Enterprise Operations Platform

**👨‍💻 Developed by [Sin Chi Chiu](mailto:peterchiu@mapstudiousa.com) · [MAP Studio USA](https://www.mapstudiousa.com)** · ☎ +1-949-331-6528

**Run your entire company with chat prompts.** NexaCrew is a self-hosted, AI-native ERP · POS · Inventory (IMS) · Warehouse (WMS) · Workforce · Visitor-Management platform engineered to data-center standards — one installer, one server, and every workstation, kiosk and hand-held device in your facility comes online.

> ERP + POS + Inventory Management + Warehouse Management + HR + Visitor Kiosk + Access Control + AI Agents — unified in a single platform you own and operate on your own hardware. No cloud lock-in. No per-seat SaaS fees.

---

## 🚀 Why NexaCrew

| | |
|---|---|
| 🧠 **Prompt-Driven Operations** | Control company processes in plain language — *"8 pallets of mixed Chromebooks arrived from supplier X, receive and stage for grading"* — and the AI agent executes the receiving, inventory and QC workflows, committing ISO-controlled records for every step. |
| 🏭 **Custom-Built SOPs** | Model YOUR operation: build controlled registers, test matrices, cross-form cascades and standard operating procedures per company. Ships with industry operation packages (electronics refurbishing/R2v3, restaurant, supermarket, warehouse) and lets AI generate new ones from a chat description. |
| 🧾 **ISO-Grade Record Control** | Every entry is attributable, time-stamped and tamper-evident — aligned with ISO 9001 / 14001 / 45001 §7.5 documented-information requirements. Operator identity is verified by **live face capture** chained into the audit log. |
| 🖥️ **Kiosk & Station Modes** | Any Chromebook, iPad or Android tablet becomes a dedicated terminal: **Station mode** locks a workbench to one register (scan → test → commit); **Kiosk mode** runs self-service POS, worker time-clock check-in and visitor reception unattended. |
| 🙋 **Visitor Management with Face Recognition** | Returning visitors are recognized by a real server-side face-recognition stack (dlib 128-d encodings + DeepFace verification + OpenCV) — one glance at the kiosk and their record is retrieved, host notified, badge issued with QR access control. |
| 👷 **Workforce & Access Control** | HR enrollment auto-provisions worker logins, prints ID badges with opaque QR credentials (zero PII in the code), drives the time-clock, payroll batches, door-access decisions and badge lifecycle — issue, suspend, revoke, all audited. |
| � **Inventory & Warehouse Management (IMS / WMS)** | Full inventory lifecycle — receiving, grading/QC, put-away, stock registers and lot tracking — on visual **facility maps you draw yourself**: warehouses, zones and racks with structured storage-location codes. Barcode/serial capture by camera at the workbench, cross-form cascades so goods flow receiving → QC → inventory without re-keying, and AI prompts like *"8 pallets arrived from supplier X — receive and stage for grading"* executed end-to-end. |
| �🛒 **Point of Sale** | Touch-first POS with barcode/QR scanning, receipts, cash-drawer flows and inventory integration — runs on the same platform, same audit trail. |
| 🔄 **Zero-Touch Fleet Updates** | Clients auto-update from your server: version beacon, checksummed package download, atomic install, automatic restart. One `curl` command installs a Linux client; one `.bat` installs Windows. |
| 🗣️ **Multilingual** | English · 繁體中文 · Español across the console, kiosks and operation logs — query your ops log in any of them. |

## 🏗️ Architecture — Engineered Like a Data Center

- **Single-binary style deployment**: FastAPI + SQLite(WAL) + vanilla-JS PWA frontend — no external database, message broker or container orchestration required. Runs on anything from a mini-PC to a rack server.
- **HTTPS everywhere**: parallel TLS listener for camera-capable kiosks; opaque device credentials for unattended terminals — never user sessions.
- **Reliability discipline**: timeouts + retry with backoff on every external call, graceful shutdown, idempotent mutations, health endpoints, structured audit logging with face-ID chaining.
- **Licensing & fleet control**: seat-enforced license keys bound to devices, live client inventory (version/OS/hardware), remote configuration and update push.
- **Cluster-ready**: LAN auto-discovery, controller/worker roles, GPU-aware AI provider routing (local models or hosted APIs).

## ⚡ Quick Start

**Server (Windows / macOS / Linux)** — Python 3.9+ (3.12 recommended):

```bash
git clone https://github.com/bomberbohk/NexaCrew.git
cd NexaCrew
python start.py        # creates venv, installs deps, starts server + tray
```

Console: `https://<server>:8443` (HTTPS) — first run creates the admin account.

**Client workstations** — from the server's login page, download the one-click installer, or on Linux/macOS:

```bash
curl -fsSL "http://<server>:8600/api/installer-sh?key=<LICENSE-KEY>" | bash
```

**Kiosks (ChromeOS / iPad / Android)** — open `https://<server>:8443/?station=<CODE>`, `/checkin`, `/visitor` or `/kiosk` and Add to Home Screen. Devices enroll automatically and appear in the fleet console.

## 📸 Feature Highlights

- **AI agent runs**: natural-language operations executed against your registers, with linked-record cascades (receiving → data-security log → QC) so staff never re-key data
- **Badge-QR sign-in** with automatic operator face capture for the operations log
- **Camera watchdog**: warns the operator when the workstation camera is blocked — identity attribution is continuous, not just at login
- **Approvals, scheduling, payroll CSV, purchasing/ERP ledgers, email + calendar integration, backups, bilingual op-log query**

## 🔐 Security Posture

Parameterized queries throughout · bcrypt-hashed credentials · HTTP-only strict-SameSite sessions · single-active-session per worker · brute-force rate limiting · encrypted badge tokens (Fernet) with SHA-256 lookups · least-privilege device credentials · full audit trail on every privileged action.

## 📄 License

Proprietary — © MAP Studio. Developed by **Sin Chi Chiu**.
Licensing, seats and support: [www.mapstudiousa.com](https://www.mapstudiousa.com) · peterchiu@mapstudiousa.com

---

*NexaCrew — the operations platform that treats your business like a mission-critical system, because it is.*
