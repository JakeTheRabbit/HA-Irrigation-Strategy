import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ArcGauge, arcAngle } from "@/components/primitives/arc-gauge";
import { HealthRing, StabilityRing, announceThrottle } from "@/components/primitives/ring";
import { CapacityBar } from "@/components/primitives/capacity-bar";
import { StepRail } from "@/components/primitives/step-rail";
import { HoldButton, holdController, isRealPress } from "@/components/primitives/hold-button";
import { Sentence, phoneRows, type SentenceToken } from "@/components/primitives/sentence";
import { wakeLockSupported } from "./wake-lock";

const html = (el: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(el);

describe("CapacityBar", () => {
  test("CapacityBar marks overflow with hatch and triangle", () => {
    const out = html(
      createElement(CapacityBar, {
        segments: [
          { id: "z1", label: "Zone 1", lph: 540, tone: "water" },
          { id: "z2", label: "Zone 2", lph: 522, tone: "water" },
        ],
        capacityLph: 900,
        caption: "Zones 1 and 2 together ask 1062 L/h of a 900 L/h pump",
      }),
    );
    expect(out).toContain('role="img"');
    expect(out).toContain('aria-label="Zones 1 and 2 together ask 1062 L/h of a 900 L/h pump"');
    expect(out).toContain("capacity-overflow");
    expect(out).toContain("▲");
    // Capacity line sits at 900 / 1062 of the bar, the overflow takes the rest.
    expect(out).toContain("left:84.746%");
    expect(out).toContain("width:15.254%");
  });

  test("no overflow inside capacity", () => {
    const out = html(
      createElement(CapacityBar, {
        segments: [{ id: "z1", label: "Zone 1", lph: 540, tone: "water" }],
        capacityLph: 900,
        caption: "Zone 1 uses 540 of 900 L/h",
      }),
    );
    expect(out).not.toContain("capacity-overflow");
    expect(out).not.toContain("▲");
    expect(out).toContain("width:60%");
  });
});

describe("ArcGauge", () => {
  test("ArcGauge data-angle 33 for 62 in 40..160", () => {
    expect(arcAngle(62, 40, 160)).toBe(33);
    const out = html(
      createElement(ArcGauge, { value: 62, min: 40, max: 160, band: [80, 120], tone: "warn", label: "Zone 2 flow ratio", unit: "%" }),
    );
    expect(out).toContain('data-angle="33"');
    expect(out).toContain('role="img"');
    expect(out).toContain('aria-label="Zone 2 flow ratio 62%, target band 80–120%"');
  });

  test("clamps outside the scale", () => {
    expect(arcAngle(10, 40, 160)).toBe(0);
    expect(arcAngle(200, 40, 160)).toBe(180);
  });
});

describe("rings", () => {
  test("HealthRing renders pct and label", () => {
    const out = html(createElement(HealthRing, { pct: 94, label: "System health" }));
    expect(out).toContain(">94<");
    expect(out).toContain("System health");
    expect(out).toContain('aria-label="System health 94%"');
  });

  test("StabilityRing shows the value, caption and state", () => {
    const out = html(
      createElement(StabilityRing, { value: "5.96", caption: "pH in 7.00 buffer", state: "settling", progress: 0.4 }),
    );
    expect(out).toContain("5.96");
    expect(out).toContain("pH in 7.00 buffer");
    expect(out).toContain("Settling…");
    expect(out).toContain('data-state="settling"');
    expect(out).toContain('role="status"');
  });

  test("announceThrottle allows one announcement per 5 s", () => {
    expect(announceThrottle(0, null)).toBe(true);
    expect(announceThrottle(1_000, 0)).toBe(false);
    expect(announceThrottle(4_999, 0)).toBe(false);
    expect(announceThrottle(5_000, 0)).toBe(true);
    // Reaching Steady is announced at once.
    expect(announceThrottle(1_000, 0, true)).toBe(true);
  });
});

describe("StepRail", () => {
  const steps = [
    { title: "Choose probe", detail: "F2 feed pH" },
    { title: "Buffer 1", detail: "buffer 7.00" },
    { title: "Buffer 2", detail: "buffer 4.00" },
  ];
  test("StepRail marks current step", () => {
    const out = html(createElement(StepRail, { steps, current: 2 }));
    expect(out).toContain('data-current="2"');
    expect(out).toMatch(/<li[^>]*aria-current="step"[^>]*>.*Buffer 1/);
    expect(out).toMatch(/<li[^>]*data-done=""[^>]*>.*Choose probe/);
    expect(out.match(/aria-current/g)).toHaveLength(1);
  });

  test("compact rail shows bars and the current step heading", () => {
    const out = html(createElement(StepRail, { steps, current: 2, compact: true }));
    expect(out).toContain('data-compact=""');
    expect(out).toMatch(/<h2[^>]*tabindex="-1"[^>]*>Buffer 1<\/h2>/);
  });
});

describe("holdController", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  const make = (mode: "while-held" | "hold-to-confirm", maxSeconds = 30) => {
    const onStart = vi.fn();
    const onStop = vi.fn();
    return { onStart, onStop, hold: holdController({ mode, maxSeconds, onStart, onStop }) };
  };

  test("while-held starts on press and stops once on release", () => {
    const { onStart, onStop, hold } = make("while-held");
    hold.press();
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(hold.active()).toBe(true);
    hold.release("pointerup");
    hold.release("pointerup");
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(hold.active()).toBe(false);
  });

  test.each(["pointerup", "pointercancel", "lostpointercapture", "blur", "visibilitychange", "keyup", "unmount"] as const)(
    "while-held stops once on %s",
    (reason) => {
      const { onStop, hold } = make("while-held");
      hold.press();
      hold.release(reason);
      // A second end of the same hold (pointerup after lostpointercapture, blur after hidden) is ignored.
      hold.release("pointerup");
      hold.release("unmount");
      vi.advanceTimersByTime(60_000);
      expect(onStop).toHaveBeenCalledTimes(1);
    },
  );

  test("hold releases on visibility hidden", () => {
    const { onStart, onStop, hold } = make("while-held");
    hold.press();
    hold.release("visibilitychange");
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  test("while-held stops at maxSeconds", () => {
    const { onStop, hold } = make("while-held", 20);
    hold.press();
    vi.advanceTimersByTime(19_999);
    expect(onStop).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(hold.active()).toBe(false);
    // The finger lifting afterwards does not stop it again.
    hold.release("pointerup");
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  test("a second press while held does not start twice", () => {
    const { onStart, onStop, hold } = make("while-held");
    hold.press();
    hold.press();
    expect(onStart).toHaveBeenCalledTimes(1);
    hold.release("pointerup");
    hold.press();
    hold.release("pointerup");
    expect(onStart).toHaveBeenCalledTimes(2);
    expect(onStop).toHaveBeenCalledTimes(2);
  });

  test("hold-to-confirm fires after 1.5 s and not on a short tap", () => {
    const { onStart, hold } = make("hold-to-confirm");
    hold.press();
    vi.advanceTimersByTime(1_000);
    hold.release("pointerup");
    vi.advanceTimersByTime(5_000);
    expect(onStart).not.toHaveBeenCalled();

    hold.press();
    vi.advanceTimersByTime(1_499);
    expect(onStart).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(onStart).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(10_000);
    hold.release("pointerup");
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  test("hold-to-confirm is cancelled by visibility hidden", () => {
    const { onStart, hold } = make("hold-to-confirm");
    hold.press();
    vi.advanceTimersByTime(1_000);
    hold.release("visibilitychange");
    vi.advanceTimersByTime(5_000);
    expect(onStart).not.toHaveBeenCalled();
  });

  test("only a real pointer press or Space counts, never Enter or a synthetic event", () => {
    expect(isRealPress({ type: "pointerdown", isTrusted: true, button: 0, isPrimary: true })).toBe(true);
    expect(isRealPress({ type: "pointerdown", isTrusted: false, button: 0, isPrimary: true })).toBe(false);
    expect(isRealPress({ type: "pointerdown", isTrusted: true, button: 2, isPrimary: true })).toBe(false);
    expect(isRealPress({ type: "pointerdown", isTrusted: true, button: 0, isPrimary: false })).toBe(false);
    expect(isRealPress({ type: "keydown", isTrusted: true, key: " ", repeat: false })).toBe(true);
    expect(isRealPress({ type: "keydown", isTrusted: true, key: " ", repeat: true })).toBe(false);
    expect(isRealPress({ type: "keydown", isTrusted: true, key: "Enter", repeat: false })).toBe(false);
    expect(isRealPress({ type: "keydown", isTrusted: false, key: " ", repeat: false })).toBe(false);
    expect(isRealPress({ type: "click", isTrusted: true })).toBe(false);
  });
});

describe("HoldButton", () => {
  test("HoldButton disabled shows reason", () => {
    const out = html(
      createElement(HoldButton, {
        mode: "while-held",
        label: "Hold to prime",
        srLabel: "Part A pump runs only while held",
        maxSeconds: 30,
        disabledReason: "Dosing is paused for F2",
        onStart: () => {},
      }),
    );
    expect(out).toContain('aria-disabled="true"');
    expect(out).toContain("Dosing is paused for F2");
    expect(out).toMatch(/aria-describedby="[^"]+"/);
    expect(out).toContain('data-state="disabled"');
  });

  test("enabled button names the visible label and the spoken one", () => {
    const out = html(
      createElement(HoldButton, {
        mode: "hold-to-confirm",
        label: "Hold for test shot",
        srLabel: "Hold 1.5 seconds to start one test shot",
        maxSeconds: 60,
        onStart: () => {},
      }),
    );
    expect(out).not.toContain("aria-disabled");
    expect(out).toContain("Hold for test shot");
    expect(out).toContain('class="sr-only"');
    expect(out).toContain("Hold 1.5 seconds to start one test shot");
    expect(out).toContain('data-mode="hold-to-confirm"');
  });
});

describe("Sentence", () => {
  const parts = (): (string | SentenceToken)[] => [
    "Tell",
    { id: "who", kind: "select", label: "Who to tell", value: "ben", options: [{ value: "ben", label: "Ben's phone" }, { value: "sam", label: "Sam's phone" }], onChange: () => {} },
    "when",
    { id: "what", kind: "select", label: "Reading", value: "f2z1", options: [{ value: "f2z1", label: "F2 Zone 1 moisture" }], onChange: () => {} },
    "is",
    { id: "cmp", kind: "select", label: "Above or below", value: "below", options: [{ value: "above", label: "above" }, { value: "below", label: "below" }], onChange: () => {} },
    { id: "limit", kind: "number", label: "Threshold", value: 30, unit: "%", min: 0, max: 100, step: 1, onChange: () => {} },
    "for",
    { id: "for", kind: "number", label: "Minutes", value: 10, unit: "min", min: 1, max: 1440, step: 1, onChange: () => {} },
    ",",
    { id: "at", kind: "time", label: "From", value: "06:00", onChange: () => {} },
    ".",
  ];

  test("Sentence renders selects inline on desktop and labelled native selects on phone", () => {
    const desktop = html(createElement(Sentence, { parts: parts(), phone: false, ariaLabel: "New rule" }));
    expect(desktop).toContain('aria-label="New rule"');
    expect(desktop).not.toContain("<select");
    expect(desktop).toContain('aria-haspopup="listbox"');
    expect(desktop).toContain('aria-label="Who to tell: Ben&#x27;s phone"');
    expect(desktop).toContain(">Ben&#x27;s phone<");
    expect(desktop).toMatch(/<input[^>]*type="number"[^>]*aria-label="Threshold"/);
    expect(desktop).toMatch(/<input[^>]*type="time"[^>]*aria-label="From"/);

    const phone = html(createElement(Sentence, { parts: parts(), phone: true, ariaLabel: "New rule" }));
    expect(phone).not.toContain("aria-haspopup");
    expect(phone.match(/<select/g)).toHaveLength(3);
    expect(phone).toMatch(/<select[^>]*aria-label="Who to tell"/);
    expect(phone).toMatch(/<option value="sam">Sam&#x27;s phone<\/option>/);
    expect(phone).toMatch(/<input[^>]*type="number"[^>]*aria-label="Threshold"/);
    expect(phone).toContain(">Tell<");
  });

  test("phone rows start at each word and drop rows without controls", () => {
    const rows = phoneRows(parts());
    expect(rows.map((r) => [r.text, r.tokens.map((t) => t.id)])).toEqual([
      ["Tell", ["who"]],
      ["when", ["what"]],
      ["is", ["cmp", "limit"]],
      ["for", ["for"]],
      ["", ["at"]],
    ]);
  });

  test("static tokens render as text or a link", () => {
    const out = html(
      createElement(Sentence, {
        parts: ["Tell", { id: "who", kind: "static", label: "Who to tell", text: "Ben's phone", href: "#/settings/notifications" }],
        phone: false,
        ariaLabel: "Rule",
      }),
    );
    expect(out).toContain('href="#/settings/notifications"');
    expect(out).toContain("Ben&#x27;s phone");
  });
});

describe("wake lock", () => {
  test("useWakeLock reports unsupported without navigator.wakeLock", () => {
    expect(wakeLockSupported(undefined)).toBe(false);
    expect(wakeLockSupported({} as Navigator)).toBe(false);
    expect(wakeLockSupported({ wakeLock: { request: () => Promise.resolve() } } as unknown as Navigator)).toBe(true);
  });
});
