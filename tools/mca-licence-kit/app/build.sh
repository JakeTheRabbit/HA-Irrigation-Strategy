#!/usr/bin/env bash
# Build the "Grow Licence Intake" APK without Gradle or the Google SDK download host.
#
# Needs (Ubuntu/Debian):  apt-get install aapt dalvik-exchange apksigner zipalign android-sdk-platform-23 openjdk-17-jdk
#                         python3 with Pillow (for the launcher icon)
#
# Recipient email: put it in app/recipient.local (one line, git-ignored) or set MCA_INTAKE_RECIPIENT.
# It is built into the APK only; it is never committed.
#
# Signing key: KEYSTORE (default ~/.mca-intake/release.keystore) is created on the first build.
# KEEP IT. An update must be signed with the same key, or Android refuses to install it over the old app.
#
# Output: app/dist/grow-licence-intake-<version>.apk
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="$(cd "$HERE/.." && pwd)"
PLATFORM="${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}"
KEYSTORE="${KEYSTORE:-$HOME/.mca-intake/release.keystore}"
KEYPASS="${KEYPASS:-mca-intake}"
VERSION="$(sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' "$HERE/android/AndroidManifest.xml")"
OUT="$HERE/build"
DIST="$HERE/dist"

RECIPIENT="${MCA_INTAKE_RECIPIENT:-}"
if [[ -z "$RECIPIENT" && -f "$HERE/recipient.local" ]]; then RECIPIENT="$(head -n1 "$HERE/recipient.local" | tr -d '[:space:]')"; fi
if [[ -z "$RECIPIENT" ]]; then echo "WARNING: no recipient set; the app will ask for an address on each send." >&2; fi

for t in aapt dalvik-exchange zipalign apksigner javac keytool python3; do
  command -v "$t" >/dev/null || { echo "Missing tool: $t" >&2; exit 1; }
done
[[ -f "$PLATFORM" ]] || { echo "Missing $PLATFORM (apt-get install android-sdk-platform-23)" >&2; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"/{assets/web,res/drawable,gen,classes} "$DIST"

# 1. Web assets: the page, the questionnaire (single source in skill/assets) and the build config.
cp "$HERE/web/index.html" "$OUT/assets/web/index.html"
python3 - "$KIT/skill/assets/questionnaire.json" "$OUT/assets/web/questions.js" "$OUT/assets/web/config.js" "$RECIPIENT" "$VERSION" <<'PY'
import json, sys
src, qjs, cjs, recipient, version = sys.argv[1:6]
q = json.load(open(src, encoding="utf-8"))
ids = [x["id"] for s in q["sections"] for x in s["questions"]]
assert len(ids) == len(set(ids)), "duplicate question ids"
open(qjs, "w", encoding="utf-8").write("window.QUESTIONNAIRE=" + json.dumps(q, ensure_ascii=False) + ";\n")
open(cjs, "w", encoding="utf-8").write("window.INTAKE_CONFIG=" + json.dumps({"recipient": recipient, "app_version": version}) + ";\n")
print(f"questionnaire v{q['version']}: {len(ids)} questions")
PY

# 2. Launcher icon (drawn here so no binary lives in git).
python3 - "$OUT/res/drawable/ic_launcher.png" <<'PY'
import sys
from PIL import Image, ImageDraw
S = 192
im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
d.rounded_rectangle([8, 8, S - 8, S - 8], 40, fill=(47, 107, 63, 255))
d.rounded_rectangle([52, 40, 140, 152], 10, fill=(255, 255, 255, 255))         # clipboard
d.rounded_rectangle([76, 30, 116, 52], 8, fill=(220, 230, 222, 255))
for i, y in enumerate((70, 94, 118)):
    d.ellipse([62, y, 76, y + 14], fill=(47, 107, 63, 255))
    d.rectangle([84, y + 4, 128 - (i * 10), y + 10], fill=(150, 170, 155, 255))
d.rounded_rectangle([118, 108, 150, 160], 14, fill=(240, 163, 107, 255))        # microphone
d.rectangle([131, 160, 137, 172], fill=(240, 163, 107, 255))
im.save(sys.argv[1])
PY

# 3. Resources + manifest -> unsigned APK (and R.java).
aapt package -f -m -J "$OUT/gen" -M "$HERE/android/AndroidManifest.xml" -S "$OUT/res" -A "$OUT/assets" \
  -I "$PLATFORM" -F "$OUT/app.unsigned.apk"

# 4. Java -> classes.dex (Java 8 bytecode, no lambdas: dx does not desugar them).
find "$HERE/android/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
javac -nowarn -Xlint:-options -source 8 -target 8 -encoding UTF-8 -bootclasspath "$PLATFORM" -classpath "$PLATFORM" \
  -d "$OUT/classes" @"$OUT/sources.txt"
dalvik-exchange --dex --min-sdk-version=23 --output="$OUT/classes.dex" "$OUT/classes"
(cd "$OUT" && aapt add -f app.unsigned.apk classes.dex >/dev/null)

# 5. Align and sign (v1 + v2 + v3).
if [[ ! -f "$KEYSTORE" ]]; then
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -keystore "$KEYSTORE" -storepass "$KEYPASS" -keypass "$KEYPASS" -alias intake \
    -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=Grow Licence Intake, O=MCA Licence Kit, C=NZ" >/dev/null
  echo "Created signing key $KEYSTORE - back it up."
fi
zipalign -f -p 4 "$OUT/app.unsigned.apk" "$OUT/app.aligned.apk"
APK="$DIST/grow-licence-intake-$VERSION.apk"
apksigner sign --ks "$KEYSTORE" --ks-pass "pass:$KEYPASS" --ks-key-alias intake --out "$APK" "$OUT/app.aligned.apk"
apksigner verify --print-certs "$APK" | head -3
echo "Built $APK ($(du -h "$APK" | cut -f1)), recipient: ${RECIPIENT:-<asks each time>}"
