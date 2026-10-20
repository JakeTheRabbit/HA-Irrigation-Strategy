# R4 writing guide: scaffolded lessons for a true beginner

This guide governs the R4 rewrite of every lesson in `www/learn/course/modules/*.json`. The learner is an intelligent adult who has **never grown a plant in a pot, never used Home Assistant and never wired anything**. Assume nothing. Every lesson must make sense to someone who has only seen the lessons before it on their route.

## 1. The one rule

**Nothing is used before it is explained.** A word, abbreviation, screen name, unit, product name or idea must be explained in plain words the first time it appears on the learner's route — in the narration, not only on screen. After that, use the *same* word every time (no synonyms: pick "dripper", never switch to "emitter"; pick "shot", never switch to "watering event" without saying they are the same).

Routes (a learner sees only these lessons, in this order):

| Route | Lessons |
| --- | --- |
| Operator | A1 A2 A3 A4 A5 A6 → B1 B2 B3 B4 → C1 → D1 D2 D3 D4 D5 D6 |
| Builder (Pi) | A1–A6 → B1–B4 → C1 → C2a → C3 C4 C5 C6 C7 → D1–D6 |
| Builder (PC) | A1–A6 → B1–B4 → C1 → C2b → C3 C4 C5 C6 C7 → D1–D6 |

Consequences:

- **D lessons cannot rely on C2–C7.** An operator skips them. If a D lesson needs "entity", "heartbeat", "acknowledged", "mapping" or "Watering switch", it re-explains it in one sentence ("Remember: … — or if you skipped setup, here is what that means: …").
- C2a and C2b are alternatives. C3 must not assume which one was taken.
- A term listed in the ledger below as introduced in lesson X may be used freely from lesson X+1 onwards, but **re-anchor** it briefly (half a sentence) the first time it reappears in a new lesson.

## 2. Slide shape (every slide)

Each slide is one idea. Narration follows this arc — not every beat needs its own sentence, but the order holds:

1. **Hook / link** — connect to something the learner already knows (everyday object or a previous slide). One sentence.
2. **Explain** — the new idea in plain words. Then its name. *Idea first, label second:* "Water fills the gaps between the pieces. Growers call this …".
3. **Show** — point at what is on screen: "Look at the blue line on the left…". The visual must match.
4. **Example** — concrete numbers or a concrete case. Say the arithmetic out loud, step by step.
5. **Why it matters** — one sentence on what goes wrong if you get it wrong.
6. **Bridge** — one sentence pointing to the next slide or the check question.

Length: 90–170 words of narration per slide (≈ 40–75 s at the voice speed). Longer is fine where a calculation is worked; never pad.

## 3. Language

- Short sentences. Average under 15 words; none over 25.
- Active voice, second person: "You check the probe." Not "The probe should be checked."
- Concrete before abstract. Number before formula. Picture before label.
- **Cut the hedging.** R3 repeated "does not prove / cannot establish / is not evidence" dozens of times per lesson. Say each limit **once**, where it matters, as a positive instruction: "To know the water really stopped, look at the outlet." A slide may carry at most one caveat sentence.
- Say numbers the way a person would read them aloud in narration ("sixty percent", "zero point eight millisiemens per centimetre"); the slide `body` uses digits and symbols.
- Units: say the full unit name the first time with its short form ("litres per hour — written L slash h").
- Product names (TEROS 12, Raspberry Pi, HACS, Growlink, Ubuntu, Home Assistant OS) — one plain-words sentence of what it *is* before what it does.
- New Zealand / British spelling (litre, colour, organise). Keep spoken text TTS-friendly: no parentheses, slashes, ampersands, "e.g.", "i.e." or bare symbols in `narration`. Write "for example".
- No exclamation marks, no hype, no "simply", "just", "obviously", "easy".

## 4. Check questions are part of every slide

Every slide gets a `check` — one multiple-choice question the learner answers before moving on. It tests the slide's single idea, ideally by **applying** it to a new case, not by recalling a phrase.

```json
"check": {
  "prompt": "A pot holds 2 L of substrate at 50% VWC. How much water is in it?",
  "options": [
    { "text": "1 L", "correct": true,  "feedback": "2 × 0.5 = 1 litre of water is already inside." },
    { "text": "2 L", "correct": false, "feedback": "That is the whole sample. Multiply by 0.5 first." },
    { "text": "0.5 L", "correct": false, "feedback": "0.5 is the fraction, not litres. Multiply it by 2 L." }
  ]
}
```

Rules: 2–4 options, exactly one correct, every option has feedback that **teaches** (explain why, give the fix). Distractors are real misconceptions, not jokes. Prompt ≤ 160 characters, options ≤ 90 characters each so they fit a phone screen without scrolling.

The lesson's end `quiz` (4–5 questions) stays as the graded knowledge check: new data, mixed ideas from across the lesson, same option rules. Keep `safetyCritical: true` on the existing safety questions.

## 5. What you may change in a lesson

Change: `title`, `summary`, `outcomes`, slide `title`, `body`, `narration`, `visual.title`, `visual.labels`, `visual.caption`, `visual.values` (if the numbers change, keep the same count/shape), `workedExample`, `check`, `quiz`, `practice`, `practicalTask.instructions`.

Keep fixed: lesson `id`, `module`, `route`, `prerequisites`, `sources`; slide **count**, slide `id`s and order, `visual.type`, and any other `visual` keys. The video pipeline binds pictures to these.

`body` = 2–3 short on-screen key points (≤ 70 characters each) that summarise the narration — the learner's takeaway, not a transcript.

## 6. Term ledger (route order)

"Introduce" means: first use, with a plain explanation. Each term is owned by exactly one lesson.

| Lesson | Introduces |
| --- | --- |
| A1 | pot/container · root zone · substrate (coco, stone wool) · pore spaces · oxygen for roots · drainage · evaporation · plant uptake · sensor/probe (a device that measures one small spot) · reading · zone (plants watered together) · irrigation · crop steering · demo (practice copy of the app that runs no equipment) |
| A2 | volume · VWC (volumetric water content) · percent of a sample · litres from a percentage · calibration · plant-available water (not all water is equally easy for roots) |
| A3 | saturation · drained / container capacity · reference value (a number the app compares against; Post-it) · setting (a value you type into the app) · peak (highest reading) · field capacity reference in the app |
| A4 | dryback · percentage points · relative dryback · starting reading · timestamp |
| A5 | dissolved salts · nutrients · EC (electrical conductivity) · millisiemens per centimetre (mS/cm) · meter · feed EC · tank · bulk EC · pore-water EC · runoff · lab extract · estimate · TEROS 12 (one specific moisture-and-EC probe) |
| A6 | freshness / age of a reading · stale · units and scale error (0.45 vs 45%) · placement · air gaps · probe identity (label matches room and zone) · room (a space with its own lights; holds one or more zones) |
| B1 | graph · time axis · left and right axes / scale · line · legend · day and night shading · shot (one watering event) · event marker · planning reference line (dashed) vs measured line (solid) · threshold (a trigger line) · draft (an unsaved proposal) · save · Controller (the watering software that decides when to water, explained in one line; C1 expands) |
| B2 | lights-on / lights-off · grow-day · phase · P0 morning wait · P1 ramp-up / refill · P2 maintain · P3 overnight · target · re-water threshold · emergency floor · rescue shot · forecast (planned shots) vs event record (shots that happened) |
| B3 | vegetative growth · generative growth · steering bias · endpoint · profile · slider / blend · rounding to a step |
| B4 | dripper · flow rate · L/h · runtime · seconds per hour · per plant vs per zone · catch test · delivery vs runoff vs uptake · requested vs effective runtime |
| C1 | system functions (plan, measure, supply, switch, protect) · computer / host · Home Assistant (free home-automation software that collects readings and switches equipment) · entity (one named reading or control inside Home Assistant) · integration · Crop Steering integration vs Controller app · bridge · valve · pump · filter · pressure regulator · backflow / siphon · relay / control hardware · starting load · physical shutdown · one owner per output · dashboard |
| C2a | Raspberry Pi · storage card · Raspberry Pi Imager · Home Assistant OS · image / writing an image · Ethernet · network address · port 8123 · onboarding |
| C2b | x86-64 PC · NUC · UEFI · Secure Boot · disk vs USB stick · live Ubuntu · disk image · (Ethernet, network address, port, onboarding — re-explained here because C2a is skipped) |
| C3 | entity ID · account / password / recovery · timezone · HACS · restart · app store · app repository · version matching · Start on boot · Watchdog · heartbeat · backup · encryption key / emergency kit |
| C4 | mapping · Equipment → Setup screen · supply type (valves only / pump then valves) · units check · last update · plant count · substrate per plant · drippers per plant · Save configuration · acknowledgement (the Controller's receipt) · revision |
| C5 | Watering OFF vs physical isolation · electrical isolation · supply voltage · signal protocol · firmware · rating · motor starting load · dry-run · deadheading · old timer / competing controller · read-only observation |
| C6 | commissioning · stage one equipment test · stage two supervised Controller cycle · catch cup · mL → L/h · uneven delivery · readiness checklist · enabling Watering |
| C7 | Growlink · export · migration · handover · rollback · friendly name vs real device |
| D1 | Overview screen · All zones · Selected room · zone page · header · report age · unknown state · Why / next action · Stop all · shared pump · default view · (re-explain: entity, heartbeat — operator route skipped C3) |
| D2 | Irrigation → Current day · Target source · plan-owned vs manual · saved / draft / actual lines · field help · allowed step · Review changes · Apply · readback · restore |
| D3 | Calendar · Endpoint profiles · schedule block · zone start date · day numbers · Review and save · Arm · activation · Disarm · plan hold · Recipes |
| D4 | History · Timeline · Water use · Compare runs · Grows · grow age · coverage · saved reference snapshot · estimated vs measured |
| D5 | fault · troubleshooting order (make safe → preserve → investigate → verify) · tank level sensor · conflicting evidence · acknowledgement (re-explain) · sticking valve |
| D6 | preflight · daily diary · five-part record · decision record · AI assistant · handover note · update and rollback |

Any term a writer needs that is not in the ledger: introduce it in that slide with a plain explanation and list it in the lesson's change notes.

## 7. Self-check before handing in a lesson

1. Read the narration aloud from slide 1. Underline every term. Is each one in the ledger at or before this lesson on **every** route that contains this lesson, or explained right here?
2. Does every slide's `body` match what the narration says and what the visual shows?
3. Does every slide have a `check` that applies the idea to a new case?
4. Are all numbers in narration, body, visual, workedExample, check and quiz consistent?
5. Is there at most one caveat sentence per slide?
