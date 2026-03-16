# Astro Swiper — Mobile Android App

Flutter app that SSHes into your server, tunnels to the running
`astro-swiper` Flask-SocketIO backend, and lets you classify FITS
triplets on your Android phone.

## Architecture

```
Android phone
  └── Flutter app
        ├── SSH (dartssh2)   →  your server port 22
        │     └── TCP tunnel →  server:5000 (astro-swiper)
        └── Socket.IO client →  127.0.0.1:<local-tunnel-port>
                                      ↕  WebSocket events
                              astro-swiper Flask-SocketIO
                                      ↕
                              FITS files + SQLite DB (server-side)
```

**No server changes needed.** The existing `astro-swiper` backend runs
unchanged. The app tunnels port 5000 through SSH and connects just like
the web browser does.

---

## Prerequisites

| Tool | Install |
|------|---------|
| Flutter SDK | https://docs.flutter.dev/get-started/install/linux |
| Android SDK / emulator | bundled with Android Studio, or `sdkmanager` |
| `astro-swiper` running on your server | `astro-swiper config.yaml` |

---

## One-time Setup

```bash
# From the repo root:
bash mobile/setup.sh
```

This will:
1. Run `flutter create .` to generate the Android boilerplate
2. Patch `minSdkVersion` to 21 (required by `dartssh2`)
3. Add `INTERNET` permission to `AndroidManifest.xml`
4. Run `flutter pub get`

---

## Build & Run

```bash
cd mobile

# Run on connected device / emulator (debug):
flutter run

# Build a release APK you can sideload to your phone:
flutter build apk --release
# → build/app/outputs/flutter-apk/app-release.apk
```

Transfer the APK via USB (`adb install`) or copy to phone storage.

---

## First Launch

1. Open **Astro Swiper** on your phone.
2. Fill in the SSH connection form:
   - **Hostname** — your server's IP or hostname
   - **SSH Port** — usually `22`
   - **Server Port** — port `astro-swiper` is listening on (default `5000`)
   - **Username** / **Password** — your SSH credentials
3. Tap **Connect**.
4. The app SSHes in, forwards port 5000, and connects to the
   already-running `astro-swiper` session.

> **Note:** `astro-swiper` must already be running on the server before
> you connect from the phone. Start it in a `tmux`/`screen` session so
> it persists.

---

## Using the App

| Action | How |
|--------|-----|
| Classify | Tap the labelled button (noise, skips, dots, …) |
| Undo last | Tap **Undo last** at the bottom |
| Adjust brightness | Tap ⚙ → **−** / **+** next to Brightness |
| Adjust contrast | Tap ⚙ → **−** / **+** next to Contrast |
| Zoom image | Pinch-to-zoom / pan with one finger |
| Disconnect | Tap the logout icon in the app bar |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Connection refused" or timeout | Make sure `astro-swiper` is running on the server and listening on the configured port |
| SSH auth fails | Double-check username/password; verify you can `ssh user@host` from a terminal |
| App shows "Disconnected" immediately after connecting | Server may have crashed; check server logs |
| Buttons don't appear | The `keybinds` event was not received; try reconnecting |
