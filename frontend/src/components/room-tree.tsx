import { createContext, useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { number } from "@/components/dashboard";
import { facilityRooms, irrigationMode, pickKey } from "@/lib/facility";
import { openAlerts } from "@/lib/open-alerts";
import type { Controller } from "@/lib/types";
import { useNarrow } from "@/lib/use-narrow";
import "./room-tree.css";

export interface RoomPick {
  title: string;
  /** Room ids and `pickKey(room, zone)` keys. */
  selected: Set<string>;
  onChange(next: Set<string>): void;
  onDone(): void;
  onCancel(): void;
  /** A room left out of the pick, with its zones (the room a copy comes from). */
  exclude?: string;
}

/** How a page asks the shell's room tree to pick (null ends it): the desktop sidebar's tree, or on a
 * phone a tree in a bottom sheet. */
export const RoomPickContext = createContext<(pick: RoomPick | null) => void>(() => {});

/** The menu's live room list: every room with its state, and under it every zone with its phase
 * and moisture. One click opens a room (in the section already open) or a zone's own page, so any
 * zone in the facility is one click away and the selected one is always marked.
 *
 * `pick`: the tree becomes the picker a page asks for (copy to a room, zones for a rule): every
 * row a checkbox, Done and Cancel at the foot, and the page inert meanwhile. Below 721 px the same
 * tree opens in a bottom sheet. */
export function RoomTree({
  controller,
  allRooms,
  currentZone,
  openRoom,
  openZone,
  pick = null,
}: {
  controller: Controller;
  /** The All rooms page is open (the Status menu entry marks it): no room is marked. */
  allRooms: boolean;
  /** The zone whose page is open, if one is. */
  currentZone: number | null;
  openRoom: (room: string) => void;
  openZone: (room: string, zone: number) => void;
  pick?: RoomPick | null;
}) {
  const phone = useNarrow(720);
  const sheet = useRef<HTMLDialogElement>(null);
  const picking = !!pick;

  // Whatever opened the picker gets focus back when it ends (captured before the sheet takes it).
  const opener = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (picking) opener.current = document.activeElement as HTMLElement | null;
  }, [picking]);
  // Desktop: the page waits while the tree picks. Phone: the sheet is modal by itself.
  useEffect(() => {
    if (!picking || phone) return;
    const main = document.querySelector("main");
    main?.setAttribute("inert", "");
    return () => main?.removeAttribute("inert");
  }, [picking, phone]);
  useEffect(() => {
    const dialog = sheet.current;
    if (!picking || !phone || !dialog) return;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, [picking, phone]);
  // After the cleanups above (inert off, sheet closed), so the opener can take focus again.
  useEffect(() => {
    if (!picking) return;
    return () => {
      opener.current?.focus?.();
      opener.current = null;
    };
  }, [picking]);

  const rooms = facilityRooms(controller.states, controller.rooms).filter(
    ({ room }) => room.id !== pick?.exclude,
  );
  const alerts = openAlerts(controller);
  const toggle = (key: string) => {
    if (!pick) return;
    const next = new Set(pick.selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    pick.onChange(next);
  };
  /** A pick row is a labelled checkbox; otherwise the row is a button that opens the page. */
  const row = (
    key: string,
    props: {
      className: string;
      title: string;
      open: () => void;
      current?: boolean;
      attrs: Record<string, unknown>;
    },
    children: ReactNode,
  ) =>
    pick ? (
      <label
        key={key}
        className={`${props.className} room-tree-pick`}
        title={props.title}
        {...props.attrs}
      >
        <input
          type="checkbox"
          checked={pick.selected.has(key)}
          value={key}
          onChange={() => toggle(key)}
        />
        {children}
      </label>
    ) : (
      <button
        key={key}
        type="button"
        className={props.className}
        title={props.title}
        aria-current={props.current ? "page" : undefined}
        onClick={props.open}
        {...props.attrs}
      >
        {children}
      </button>
    );

  const tree = (
    <nav
      className="room-tree"
      aria-label={pick ? pick.title : "Rooms"}
      data-picking={picking || undefined}
      onKeyDown={(event) => {
        // On phone the sheet's own cancel event answers Escape.
        if (pick && !phone && event.key === "Escape") pick.onCancel();
      }}
    >
      <span className="room-tree-heading">{pick ? pick.title : "Rooms"}</span>
      {rooms.map(({ room, view, status }) => {
        const selected = room.id === controller.roomId;
        const open = alerts.filter((alert) => alert.roomId === room.id).length;
        const flagged = open ? `. ${open} open alert${open === 1 ? "" : "s"}` : "";
        return (
          <div className="room-tree-room" key={room.id} data-room={room.id}>
            {row(
              room.id,
              {
                className: "room-tree-row",
                title: `${room.name}: ${status.text}. ${status.detail}${flagged}`,
                open: () => openRoom(room.id),
                current: selected && !allRooms && currentZone === null,
                attrs: {
                  "data-tone": status.tone,
                  "data-room": room.id,
                  "data-selected": selected || undefined,
                  "data-alerts": open || undefined,
                },
              },
              <>
                <span className="room-tree-dot" aria-hidden="true" />
                <span className="room-tree-name">{room.name}</span>
                <span className="room-tree-state">{status.text}</span>
                {open > 0 && (
                  <span className="room-tree-flag" data-flag="alert" aria-hidden="true" />
                )}
                {open > 0 && (
                  <span className="sr-only">{`, ${open} open alert${open === 1 ? "" : "s"}`}</span>
                )}
              </>,
            )}
            {view.zones.map((zone) => {
              const flag = zone.stale ? "stale" : zone.enabled === false ? "paused" : null;
              const timer = irrigationMode(controller.states, room, zone.id) === "timer";
              return row(
                pickKey(room.id, zone.id),
                {
                  className: "room-tree-row room-tree-zone",
                  title:
                    flag === "stale"
                      ? `${zone.name}: last reported reading`
                      : flag === "paused"
                        ? `${zone.name}: zone paused`
                        : timer
                          ? `${zone.name}: watered by timer programs`
                          : zone.name,
                  open: () => openZone(room.id, zone.id),
                  current: selected && currentZone === zone.id,
                  attrs: { "data-flag": flag ?? undefined },
                },
                <>
                  <span
                    className="room-tree-phase"
                    data-phase={timer ? undefined : zone.phase}
                    data-mode={timer ? "timer" : undefined}
                  >
                    {timer ? "T" : /^P[0-3]$/.test(zone.phase) ? zone.phase : "–"}
                  </span>
                  <span className="room-tree-name">{zone.name}</span>
                  <span className="room-tree-value">
                    {zone.vwc.value === null
                      ? timer
                        ? "timer"
                        : "—"
                      : `${number(zone.vwc.value)}%`}
                  </span>
                  {flag && <span className="room-tree-flag" aria-hidden="true" />}
                </>,
              );
            })}
          </div>
        );
      })}
      {pick && (
        <div className="room-tree-actions">
          <button type="button" className="room-tree-done" onClick={pick.onDone}>
            Done
          </button>
          <button type="button" className="room-tree-cancel" onClick={pick.onCancel}>
            Cancel
          </button>
        </div>
      )}
    </nav>
  );

  if (pick && phone)
    return (
      <dialog
        ref={sheet}
        className="room-tree-sheet"
        aria-label={pick.title}
        onCancel={(event) => {
          event.preventDefault();
          pick.onCancel();
        }}
      >
        {tree}
      </dialog>
    );
  return tree;
}
