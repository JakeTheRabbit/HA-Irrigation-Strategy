# Independent strategy backend review — 2026-09-08

**Final verdict: approved for the reviewed local source scope. All four Important findings and the follow-up assignment-contract issue are resolved; no remaining material finding.**

Scope: new strategy model/store/services/runtime, controller strategy consumption and setup lifecycle gates. Reviewed working tree source only. No live HA access, source changes, hardware commands, commits, or reruns of unchanged suites. Small isolated Python reproductions used existing minimal test doubles. Parent/implementer own regression tests and final fixes.

## Initial verdict: changes required

No Critical finding. Four Important findings below have been sent directly to the parent and controller/strategy implementer. References name the reviewed source positions before fixes; later formatting may move them.

### Important 1 — Persist disarm intention and its target boundary

`custom_components/crop_steering/strategy.py:220`, `:393`, `:417`.

Disarm records only status=disarming. Tick accepts any time within 120 seconds after lights-on, including the same boundary during which disarm was requested. Confirmed: activate at 10:00, disarm at 10:00:30, tick at 10:01 produces draft/release_legacy=True, despite the advertised next-boundary policy.

More seriously, startup converts a saved disarming document to error when its grow_day differs from the current boundary. Its armed_after remains set, and generic error recovery can activate it again. Confirmed: disarm an active plan at 14:00, restart at 14:00 next day after missing the release boundary; startup reports error, and the following lights-on tick reports active with one managed zone. An explicit user disarm must survive restart and error recovery. Persist a distinct release target/intention and prevent it from entering activation recovery.

### Important 2 — Revalidate strategy before every future shot

`addons/f2_control/f2_control/controller.py:1464`, `:1585`; `strategy_runtime.py:56`.

Snapshot TTL is checked once at the beginning of a room pass. All zone decisions are computed and shots then run synchronously in sequence. The usual 324-second shot outlasts a 180-second snapshot lifetime. Subsequent zones pass _blocked using the already parsed cached snapshot; _execute_shot does not refresh it. Thus an expired or newly held/released plan can still initiate later shots in the same pass.

Before each future shot, require fresh matching strategy identity/content and coherent parameters/decision. A changed plan/day should defer or recompute instead of executing the prior decision under newly refreshed metadata. This does not require changing the existing in-flight engine-kill semantics.

### Important 3 — Apply or hold default lifecycle metadata before the first loop

`addons/f2_control/f2_control/controller.py:196`, `:219`, `:567`, `:1401`.

Default startup builds all zones from a numeric range, without active/active_zone_ids, and does not apply lifecycle descriptors until the first rediscovery (default 300 seconds). Confirmed with the real constructor and fake HA: descriptor revision 2, active=false, active_zone_ids=[], engine/system/auto/zone controls ON produces runtime zones=[1], no setup_active attribute, and _blocked returns None. The same path revives removed default-zone slots before rediscovery. Initial active/tombstone/pending metadata must inhibit irrigation before any shot; archive cannot depend solely on a previously OFF control staying OFF.

### Important 4 — Match hydraulic preview to actual low-flow delivery

`custom_components/crop_steering/strategy_model.py:302`; `addons/f2_control/f2_control/controller.py:1348`.

The preview divides by configured zone flow, while _act_zone silently raises the denominator to 0.001 L/s. A valid setup of one plant, 6 L substrate, one 2 L/h dripper and a 6% shot previews 648 seconds; an isolated call to the real _act_zone captures 360 seconds (both under the 900-second cap). This underdelivers relative to the reviewed plan. The new sizing contract permits this configuration. Use the same positive-flow calculation and reject invalid zero/negative flow explicitly, or surface any intentionally retained compatibility limit in the preview.

## Positive checks and limits

Both legacy steering mode families resolve to the same canonical continuous dryback/phase EC profile parameters. Plans preserve underlying manual HA number/select settings. Explicit saved drafts arm for a subsequent local lights-on boundary, with durable controller strategy-required state and no silent legacy fallback after an activated strategy disappears. Model validation rejects foreign/archived zones, invalid endpoint ranges and relationships, gaps/overlaps, malformed days, unsupported parameters and nonfinite values. Storage keys are entry-scoped and response services resolve exact canonical room IDs.

No claim is made that HA timers, physical hardware, installation, daylight-saving edge behavior, or restart delivery have been verified on a real system. The final approval remains pending the four fixes and scoped re-review.

## Scoped fix re-review (first pass)

Findings 1, 3 and 4 are resolved in the reviewed source. Original isolated reproductions now confirm: disarm immediately after lights-on remains pending; a restart after the missed target cannot reactivate the plan and releases at the following boundary; an archived default room is gated during construction before its first loop; and low-flow actual delivery matches 648 seconds. The new disarm_after is persisted independently of generic error status. Constructor reconciliation sets a pending hold when controls are ON. Valid positive flow no longer receives a hidden denominator floor.

Finding 2 remains Important in the first preflight fix at controller.py:1446. _strategy_preflight compares against room.strategy_snapshot and then replaces that snapshot even when rejecting a changed decision. The next zone in the same old decision batch therefore compares against the new cache and passes. Confirmed two-zone reproduction: change both zones' p2_shot_size from 4 to 2; zone 1 preflight returns recompute hold, zone 2 preflight returns None. The expected comparison must remain bound to the immutable decision batch, or invalidate the remainder of the batch until decisions are rebuilt. This follow-up was sent directly to the implementer and parent.

Additional bounded review: quantized strategy endpoints/preview use room catalog steps and recheck VWC relationships; predictive P3 now converts relative-percent peak dryback into remaining VWC percentage points before dividing by measured points/hour. No additional material issue found in these deltas.

Integration startup ordering was checked at the parent's request: __init__.py awaits all forwarded platforms before strategy initialization/seeding. HA's [EntityPlatform setup implementation](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/entity_platform.py) also awaits scheduled entity-add tasks before successful setup returns. This supports normal fresh setup ordering; it does not claim actual HA platform startup was exercised locally.

Verdict remains changes required solely for finding 2's decision-batch invalidation.

## Scoped fix re-review (second pass)

Finding 2's batch cache issue is now resolved by a latched batch invalidation, cleared only at the start of a freshly computed room pass. Independent two-zone reproductions confirm both future shots remain held for changed parameters, explicit release, expired snapshot, and hold followed by recovery before the second zone. The preflight runs before pump activation. The original four Important findings are therefore resolved.

One follow-up introduced by the additional setup/strategy guard was sent to the implementer: controller _load_strategy_snapshot now requires managed zones to equal the complete active room zone set, but model normalization still accepts a partial assignment set. Align validation so save/arm reject an incomplete plan before reporting success for a plan the controller will only hold. Final review completion awaits that contract alignment.


## Final scoped closure

All four original Important findings and follow-up defects are resolved. Exact assignment-set validation now rejects partial plans before save/arm; the independent negative reproduction receives the explicit room-setup reconciliation error, while a complete single-zone plan still validates. Integration tick also holds active plans when room zone membership changes or the room is archived, preserving explicit disarm intent as the higher-priority path.

Independent verification in this review consisted of bounded reproductions of both disarm timing/restart cases, archived default startup, low-flow duration parity, all remaining-zone holds after change/release/expiration/transient error, and partial-plan rejection. No unchanged full suite was rerun. The implementer separately reports 77 combined strategy/state/add-on tests and 48 pure-engine tests passing; those counts are attributed implementation evidence, not reruns by this reviewer.

Final verdict: **approved for this source review scope**, with no remaining Critical or Important finding. This approval is not a deployment authorization or claim of live HA, physical delivery, or real DST transition testing.
