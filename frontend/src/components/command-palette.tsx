import { useEffect, useRef, useState } from "react";
import { paletteEntries, paletteKey, searchPalette, type PaletteEntry } from "@/lib/command-palette";
import type { Controller } from "@/lib/types";

const SHOWN = 12;

/** The header's "Jump to…" button and the palette it opens (also Ctrl/⌘ K, or "/" outside a
 * field): type a few letters of a page, room, zone or action, Enter opens the first. A native
 * modal dialog; closing it puts focus back where it was. */
export function CommandPalette({
  controller,
  jump,
}: {
  controller: Controller;
  jump: (entry: PaletteEntry) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const found = open ? searchPalette(paletteEntries(controller), query).slice(0, SHOWN) : [];

  const show = () => {
    const box = dialog.current;
    if (!box || box.open) return;
    const focused = document.activeElement;
    opener.current =
      focused instanceof HTMLElement && focused !== document.body ? focused : button.current;
    setQuery("");
    setActive(0);
    setOpen(true);
    box.showModal();
    input.current?.focus();
  };
  const showRef = useRef(show);
  showRef.current = show;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const panel = button.current?.closest(".app-shell") ?? document.body;
      if (paletteKey(event, panel) !== "open") return;
      event.preventDefault();
      showRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const choose = (entry: PaletteEntry | undefined) => {
    if (!entry) return;
    dialog.current?.close();
    jump(entry);
  };
  const optionId = (index: number) => `command-palette-option-${index}`;

  return (
    <>
      <button
        ref={button}
        type="button"
        className="jump-to"
        aria-keyshortcuts="Control+K Meta+K /"
        onClick={show}
      >
        Jump to…<kbd aria-hidden="true">Ctrl K</kbd>
      </button>
      <dialog
        ref={dialog}
        className="command-palette"
        aria-label="Jump to"
        onClose={() => {
          setOpen(false);
          opener.current?.focus();
        }}
        onClick={(event) => {
          // A click on the backdrop (the dialog box itself, outside its content) closes it.
          if (event.target === dialog.current) dialog.current.close();
        }}
      >
        <input
          ref={input}
          className="command-palette-input"
          role="combobox"
          aria-label="Jump to a page, room, zone or action"
          aria-expanded={found.length > 0}
          aria-controls="command-palette-list"
          aria-autocomplete="list"
          aria-activedescendant={found.length > 0 ? optionId(active) : undefined}
          placeholder="Jump to a page, room, zone or action"
          autoComplete="off"
          spellCheck={false}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const step = event.key === "ArrowDown" ? 1 : -1;
              if (found.length > 0) setActive((active + step + found.length) % found.length);
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(found[active]);
            }
          }}
        />
        <ul id="command-palette-list" role="listbox" aria-label="Places">
          {found.map((entry, index) => (
            <li
              key={`${entry.room ?? ""}${entry.hash}${entry.label}`}
              id={optionId(index)}
              role="option"
              aria-selected={index === active}
              onMouseMove={() => setActive(index)}
              onClick={() => choose(entry)}
            >
              <span className="command-palette-label">{entry.label}</span>
              <span className="command-palette-hint">{entry.hint}</span>
            </li>
          ))}
        </ul>
        {open && found.length === 0 && (
          <p className="command-palette-empty" role="status">
            Nothing matches “{query.trim()}”.
          </p>
        )}
      </dialog>
    </>
  );
}
