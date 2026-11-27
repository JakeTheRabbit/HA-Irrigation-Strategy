/** One colour per zone, the same on every legend, table dot, setup square and chart series. The
 * hues stay clear of the status colours (green, amber, red) and the P2 phase purple; styles.css
 * carries the same values as --zone-1 … --zone-6. */
export const ZONE_COLOURS = ["#3b82f6", "#ec4899", "#14b8a6", "#0e7490", "#be185d", "#78716c"];
/** The colour of the zone at this position in its room (0-based). */
export const zoneColour = (index: number) => ZONE_COLOURS[index % ZONE_COLOURS.length];
