import { useEffect, useId, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Popover } from "radix-ui";
import "./primitives.css";

export type SentenceToken =
  | {
      id: string;
      kind: "select";
      label: string;
      value: string;
      options: { value: string; label: string }[];
      onChange(v: string): void;
    }
  | {
      id: string;
      kind: "number";
      label: string;
      value: number;
      unit?: string;
      min: number;
      max: number;
      step: number;
      onChange(v: number): void;
    }
  | { id: string; kind: "time"; label: string; value: string; onChange(v: string): void }
  | { id: string; kind: "static"; label: string; text: string; href?: string };

type Part = string | SentenceToken;

const wordy = (text: string) => /[\p{L}\p{N}]/u.test(text);

/** The phone layout of a sentence: each text part starts a row and names it, and the controls
 * after it sit in that row. Text without letters or digits (",") starts an unnamed row. Text with
 * no controls after it stays as a plain text row; empty rows are dropped. */
export function phoneRows(parts: Part[]): { text: string; tokens: SentenceToken[] }[] {
  const rows: { text: string; tokens: SentenceToken[] }[] = [];
  for (const part of parts) {
    if (typeof part === "string") rows.push({ text: wordy(part) ? part.trim() : "", tokens: [] });
    else {
      if (!rows.length) rows.push({ text: "", tokens: [] });
      rows[rows.length - 1].tokens.push(part);
    }
  }
  return rows.filter((row) => row.tokens.length || row.text);
}

/** A choice as an inline button that opens a listbox: arrows, Home and End move, Enter or Space
 * picks, Escape closes and returns to the button. */
function ListboxToken({ token }: { token: Extract<SentenceToken, { kind: "select" }> }) {
  const id = useId();
  const list = useRef<HTMLUListElement>(null);
  const selected = token.options.findIndex((o) => o.value === token.value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(Math.max(0, selected));
  const current = token.options[selected];
  const choose = (i: number) => {
    setOpen(false);
    const option = token.options[i];
    if (option && option.value !== token.value) token.onChange(option.value);
  };
  const keys = (e: KeyboardEvent) => {
    const last = token.options.length - 1;
    const move = { ArrowDown: Math.min(last, active + 1), ArrowUp: Math.max(0, active - 1), Home: 0, End: last }[
      e.key
    ];
    if (move !== undefined) setActive(move);
    else if (e.key === "Enter" || e.key === " ") choose(active);
    else return;
    e.preventDefault();
  };
  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        if (next) setActive(Math.max(0, selected));
        setOpen(next);
      }}
    >
      <Popover.Trigger
        className="sentence-token"
        aria-haspopup="listbox"
        aria-label={`${token.label}: ${current?.label ?? "not set"}`}
        onKeyDown={(e) => {
          if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
          e.preventDefault();
          setActive(Math.max(0, selected));
          setOpen(true);
        }}
      >
        <span>{current?.label ?? "Choose"}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="sentence-pop"
          align="start"
          sideOffset={4}
          collisionPadding={12}
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            list.current?.focus();
          }}
        >
          <ul
            ref={list}
            role="listbox"
            tabIndex={0}
            aria-label={token.label}
            aria-activedescendant={`${id}-${active}`}
            onKeyDown={keys}
          >
            {token.options.map((option, i) => (
              <li
                key={option.value}
                id={`${id}-${i}`}
                role="option"
                aria-selected={i === selected}
                data-active={i === active ? "" : undefined}
                onPointerMove={() => setActive(i)}
                onClick={() => choose(i)}
              >
                {option.label}
                {i === selected && <Check size={15} aria-hidden="true" />}
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

type NumberTokenT = Extract<SentenceToken, { kind: "number" }>;

/** The hint for a number field's text: null when it holds a number inside the token's range. */
export function numberHint(text: string, token: NumberTokenT): string | null {
  const v = text.trim() === "" ? NaN : Number(text);
  if (Number.isFinite(v) && v >= token.min && v <= token.max) return null;
  return `Between ${token.min} and ${token.max}${token.unit ? ` ${token.unit}` : ""}`;
}

/** A number field that lets the text be cleared while typing. Only numbers inside the range are
 * passed on; anything else stays as typed with a hint saying what is allowed. */
function NumberToken({ token }: { token: NumberTokenT }) {
  const hintId = useId();
  const [text, setText] = useState(String(token.value));
  useEffect(() => setText(String(token.value)), [token.value]);
  const hint = numberHint(text, token);
  return (
    <span className="sentence-number">
      <input
        className="sentence-input"
        type="number"
        inputMode="decimal"
        aria-label={token.label}
        aria-invalid={hint ? true : undefined}
        aria-describedby={hint ? hintId : undefined}
        value={text}
        min={token.min}
        max={token.max}
        step={token.step}
        onChange={(e) => {
          setText(e.target.value);
          if (!numberHint(e.target.value, token)) token.onChange(Number(e.target.value));
        }}
      />
      {token.unit && <span className="sentence-unit">{token.unit}</span>}
      {hint && (
        <span className="sentence-hint" id={hintId} role="status">
          {hint}
        </span>
      )}
    </span>
  );
}

function Token({ token, phone }: { token: SentenceToken; phone: boolean }) {
  switch (token.kind) {
    case "select":
      return phone ? (
        <select
          className="sentence-native"
          aria-label={token.label}
          value={token.value}
          onChange={(e) => token.onChange(e.target.value)}
        >
          {token.options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <ListboxToken token={token} />
      );
    case "number":
      return <NumberToken token={token} />;
    case "time":
      return (
        <input
          className="sentence-input"
          type="time"
          aria-label={token.label}
          value={token.value}
          onChange={(e) => e.target.value && token.onChange(e.target.value)}
        />
      );
    case "static":
      return token.href ? (
        <a className="sentence-static" href={token.href}>
          {token.text}
        </a>
      ) : (
        <strong className="sentence-static">{token.text}</strong>
      );
  }
}

/** A setting written as a sentence with its choices in place ("Tell [Ben's phone] when …").
 * Desktop: one line of text with inline listboxes and fields. Phone: a row per word, each with
 * native labelled controls. */
export function Sentence({
  parts,
  phone,
  ariaLabel,
}: {
  parts: Part[];
  phone: boolean;
  ariaLabel: string;
}): JSX.Element {
  if (phone)
    return (
      <div className="sentence" data-phone="" role="group" aria-label={ariaLabel}>
        {phoneRows(parts).map((row, i) =>
          row.tokens.length ? (
            <div className="sentence-row" key={row.tokens[0].id}>
              <span className="sentence-row-word">{row.text}</span>
              <span className="sentence-row-controls">
                {row.tokens.map((token) => (
                  <Token key={token.id} token={token} phone />
                ))}
              </span>
            </div>
          ) : (
            <p className="sentence-row-text" key={`text-${i}`}>
              {row.text}
            </p>
          ),
        )}
      </div>
    );
  return (
    <div className="sentence" role="group" aria-label={ariaLabel}>
      {parts.map((part, i) =>
        typeof part === "string" ? (
          <span key={i} className="sentence-word" data-punct={wordy(part) ? undefined : ""}>
            {part}
          </span>
        ) : (
          <Token key={part.id} token={part} phone={false} />
        ),
      )}
    </div>
  );
}
