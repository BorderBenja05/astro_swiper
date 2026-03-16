#!/usr/bin/env bash
# Sets up the Flutter Android project boilerplate in mobile/
# Run this once from the repo root: bash mobile/setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Check Flutter is available
if ! command -v flutter &>/dev/null; then
  echo "ERROR: flutter not found. Install Flutter SDK first: https://docs.flutter.dev/get-started/install"
  exit 1
fi

echo "==> Initialising Flutter project in $(pwd) ..."
flutter create . \
  --project-name astro_swiper_mobile \
  --org com.astroswiper \
  --platforms android \
  2>&1 | grep -v "^  •"

# Our lib/ files take precedence; flutter create would have regenerated lib/main.dart
# Restore our version (flutter create overwrites it)
echo "==> Restoring custom lib/ sources ..."
# Nothing to do — git will keep our files. The only conflict is lib/main.dart which
# flutter create overwrites; re-checkout from git:
git checkout -- lib/ 2>/dev/null || true

# Bump minSdkVersion to 21 (required by dartssh2)
GRADLE="android/app/build.gradle"
if grep -q "minSdkVersion flutter.minSdkVersion" "$GRADLE" 2>/dev/null; then
  sed -i 's/minSdkVersion flutter.minSdkVersion/minSdkVersion 21/' "$GRADLE"
  echo "==> Patched $GRADLE: minSdkVersion → 21"
elif grep -q "minSdk = flutter.minSdkVersion" "$GRADLE" 2>/dev/null; then
  sed -i 's/minSdk = flutter.minSdkVersion/minSdk = 21/' "$GRADLE"
  echo "==> Patched $GRADLE: minSdk → 21"
else
  echo "WARN: Could not find minSdkVersion in $GRADLE — set it to 21 manually."
fi

# Add INTERNET permission to AndroidManifest if not present
MANIFEST="android/app/src/main/AndroidManifest.xml"
if ! grep -q "INTERNET" "$MANIFEST" 2>/dev/null; then
  sed -i 's|<manifest|<manifest\n    <uses-permission android:name="android.permission.INTERNET"/>|' "$MANIFEST"
  echo "==> Added INTERNET permission to $MANIFEST"
else
  echo "==> INTERNET permission already present in $MANIFEST"
fi

echo ""
echo "==> Running flutter pub get ..."
flutter pub get

echo ""
echo "All done! To build and run:"
echo "  cd mobile"
echo "  flutter run           # with device/emulator connected"
echo "  flutter build apk     # produce mobile/build/app/outputs/flutter-apk/app-release.apk"
