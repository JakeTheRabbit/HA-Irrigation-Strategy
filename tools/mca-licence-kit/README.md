# MCA licence kit

A kit to prepare New Zealand Medicinal Cannabis Agency (MCA) licence applications for indoor
grow facilities: new licences, amendments that add a location, and renewals.

It is separate from the irrigation controller. Nothing in this folder is loaded by Home
Assistant, the add-on or the dashboard.

| Folder | What it is |
| --- | --- |
| `skill/` | The `mca-licence-builder` Claude skill: workflow, MCA reference, audit checklist, email templates, data template and scripts |
| `app/` | "Grow Licence Intake", an Android app that asks the questionnaire, takes spoken answers, photos, GPS and a site layout, and sends the result by email |

## Install the skill

Claude Code: copy `skill/` to `~/.claude/skills/mca-licence-builder/`.

Claude.ai: zip the `skill/` folder (the zip must contain `SKILL.md` at the top of the
`mca-licence-builder/` folder) and upload it in Settings, Capabilities, Skills.

Then ask, for example: "Use the MCA licence builder on this intake.json".

## Build the app

```bash
sudo apt-get install -y aapt dalvik-exchange apksigner zipalign android-sdk-platform-23 python3-pil
```

```bash
echo "you@example.com" > tools/mca-licence-kit/app/recipient.local
```

```bash
tools/mca-licence-kit/app/build.sh
```

The APK is in `app/dist/`. The build needs no Gradle and no Google SDK download.
`recipient.local`, `build/`, `dist/` and keystores are git-ignored.

**Keep the signing key** (`~/.mca-intake/release.keystore`, or the path in `KEYSTORE`).
Android installs an update over the old app only when the same key signs it. Without the key,
the user must uninstall the old app, and the saved interviews on the phone are lost.

## Use the app (ASD-STE100)

1. Install the APK on the Android phone. Allow "install unknown apps" for the browser or Files app.
2. Open "Grow Licence Intake". Tap **New interview**.
3. Read each question to the customer. Tap **Speak**. Say the answer in full.
4. Tap **Not known** when the customer does not know. Say who knows.
5. Tap **Take photo** for each document and site item that the question names.
6. Go to **Documents and drawing**. Set the size of the licensed area. Add each building, gate
   and camera. Drag each item to its position. Set the size of each building.
7. Tap **Review**. Do the missing required questions, or send now and finish later.
8. Tap **Send**. The email app opens with the answers, `intake.json`, the drawings and the
   photos. Check the email. Tap send.

The interview stays saved on the phone. Open it again to add answers and send again.

## Use the result

```bash
python3 tools/mca-licence-kit/skill/scripts/intake_to_yaml.py intake.json -o cases/<name>/application_data.yaml
```

```bash
python3 tools/mca-licence-kit/skill/scripts/readiness_check.py cases/<name>/application_data.yaml
```

```bash
python3 tools/mca-licence-kit/skill/scripts/floorplan.py cases/<name>/application_data.yaml -o cases/<name>/plans
```

Keep `cases/` outside this public repository. It holds private customer data.

## Test data

`skill/assets/example_intake.json` is a fictional facility for testing the scripts.
