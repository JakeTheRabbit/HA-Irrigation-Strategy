#!/usr/bin/env bash
# Stopping the controller app in the middle of a real shot must close what the shot opened.
#
#   bash tests_container/stop_mid_shot.sh <controller image> [seconds each answer waits, default 1]
#
# The image runs as Supervisor runs it (its own init, `/run.sh`, then the controller) against
# fake_ha_server.py. Its first pass fires a P2 top-up of about 87 s on zone 1 (pump, main line and
# valve). From the valve's switch-on every answer from "Home Assistant" waits, so closing up takes
# far longer than 3 s. Six seconds into the shot, `docker stop -t 30` (the app's `timeout: 30`).
# Passes when the valve's turn_off arrives after the stop, the log says the shot in flight was
# switched off, and the container exits 0 inside the 30 s. The stop path keeps inside its 25 s
# budget however long the answers wait, but the longer they wait the less of the close and its
# read-back fits in it: what is not confirmed off stays recorded for the next start and the
# "switched off" line is not logged, so this check is for answers up to about 2 s. Needs Docker;
# build with
#   docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 \
#     -t crop-steering-controller addons/f2_control
set -u
export MSYS_NO_PATHCONV=1
IMG=$1
DELAY=${2:-1}
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=stop-mid-shot-$$
HA=$RUN-ha CTL=$RUN-ctl VOL=$RUN-data
cleanup() {
  docker rm -f "$HA" "$CTL" >/dev/null 2>&1
  docker volume rm "$VOL" >/dev/null 2>&1
  docker network rm "$RUN" >/dev/null 2>&1
}
trap cleanup EXIT
docker network create "$RUN" >/dev/null
docker volume create "$VOL" >/dev/null
docker run --rm -i -v "$VOL:/data" --entrypoint sh "$IMG" -c 'cat > /data/options.json' <<'EOF'
{"num_zones": 1, "lights_on_hour": 0, "lights_off_hour": 24, "enable_flag": "input_boolean.engine",
 "loop_seconds": 5, "flow_lps": 0.002,
 "hardware": {"pump": "switch.pump", "mainline": "switch.main_line", "valves": {"1": "switch.zone_1_valve"}}}
EOF
SEED='{"input_boolean.engine": "on", "switch.crop_steering_room_active": "on",
 "switch.crop_steering_zone_1_enabled": "on",
 "sensor.crop_steering_vwc_zone_1": ["30", {"unit_of_measurement": "%"}],
 "sensor.crop_steering_ec_zone_1": ["3.0", {"unit_of_measurement": "mS/cm"}],
 "switch.pump": "off", "switch.main_line": "off", "switch.zone_1_valve": "off"}'
docker create --name "$HA" --network "$RUN" -e SEED="$SEED" -e DELAY="$DELAY" -e SLOW_AFTER=switch.zone_1_valve \
  --entrypoint python3 "$IMG" -u /fake_ha_server.py >/dev/null
tar -C "$HERE" -cf - fake_ha_server.py | docker cp - "$HA:/"
docker start "$HA" >/dev/null
docker run -d --name "$CTL" --network "$RUN" -e HA_URL="http://$HA:8123/api" -e HA_TOKEN=test \
  -v "$VOL:/data" "$IMG" >/dev/null
echo "image $IMG, S6_CMD_RECEIVE_SIGNALS=$(docker inspect "$IMG" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | sed -n 's/^S6_CMD_RECEIVE_SIGNALS=//p')"
for _ in $(seq 1 90); do docker logs "$HA" 2>&1 | grep -q "zone_1_valve on:" && break; sleep 1; done
docker logs "$HA" 2>&1 | grep -q "zone_1_valve on:" || { echo "FAIL: no shot started"; docker logs "$CTL"; exit 1; }
sleep 6
start=$(date +%s.%N)
docker stop -t 30 "$CTL" >/dev/null
took=$(awk -v a="$start" -v b="$(date +%s.%N)" 'BEGIN { printf "%.2f", b - a }')
code=$(docker inspect "$CTL" --format '{{.State.ExitCode}}')
ended=$(docker inspect "$CTL" --format '{{.State.FinishedAt}}')
echo "docker stop -t 30 took $took s, exit code $code, container ended $ended"
echo "-- controller log from the shot on"
docker logs -t "$CTL" 2>&1 | sed -n '/FIRE/,$p'
echo "-- service calls Home Assistant received"
docker logs "$HA" 2>&1 | grep -E "CALL|on:"
fail=0
docker logs "$HA" 2>&1 | sed -n '/zone_1_valve on:/,$p' | grep -q 'turn_off {"entity_id": "switch.zone_1_valve"}' \
  || { echo "FAIL: the valve was never switched off"; fail=1; }
docker logs "$CTL" 2>&1 | grep -q "stopping: switched off" || { echo "FAIL: the stop path did not finish"; fail=1; }
[ "$code" = 0 ] || { echo "FAIL: exit code $code"; fail=1; }
awk -v t="$took" 'BEGIN { exit !(t < 30) }' || { echo "FAIL: not stopped inside 30 s"; fail=1; }
[ "$fail" = 0 ] && echo "PASS"
exit "$fail"
