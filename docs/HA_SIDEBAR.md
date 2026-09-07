# Home Assistant sidebar

When opened inside a compatible Home Assistant shell, Crop Steering temporarily collapses the HA sidebar. Use **Home Assistant** at the bottom of Crop Steering's navigation, or the house button in its top bar, to open the HA menu over the workspace. The top-bar button stays available on mobile.

Leaving Crop Steering restores the prior kiosk state. This does not change Home Assistant's saved sidebar preference. Standalone demos and unsupported or cross-origin embeddings retain their normal navigation.

## Implementation references

The connector independently uses Home Assistant's temporary kiosk/menu interface, the mechanism used by Music Assistant. It does not copy the Music Assistant application or change HA's parent styles.

- [Music Assistant's HA messaging integration](https://github.com/music-assistant/frontend/blob/362b321da460f8d234c1abbfd007eb19e26d7859/src/plugins/homeassistant.ts): ingress subscription with `kioskMode` and `home-assistant/toggle-menu`.
- [Home Assistant ingress handler](https://github.com/home-assistant/frontend/blob/c3cc2217bfd3b2ac576da2a147a4679a3af6b1a8/src/panels/app/ha-panel-app.ts): subscription cleanup restores temporary kiosk mode.
- [Home Assistant sidebar state](https://github.com/home-assistant/frontend/blob/c3cc2217bfd3b2ac576da2a147a4679a3af6b1a8/src/state/sidebar-mixin.ts): temporary `hass-kiosk-mode` is separate from persisted sidebar docking.

Ingress uses the host messaging interface. The standard same-origin iframe panel uses HA's kiosk and menu events directly, because that panel does not implement ingress messages. It checks host capabilities before hiding anything. No cross-origin parent access is attempted beyond guarded capability discovery.

`frontend/scripts/verify-ha-shell.mjs` checks desktop/mobile menu recovery, restoring prior state when leaving, preserving preexisting kiosk mode, and standalone behavior against an isolated host fixture. Compatibility with every HA companion app and third-party kiosk extension is not implied.
