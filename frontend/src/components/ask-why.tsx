import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UiTip } from "@/components/info-tip";
import { time as clock } from "@/components/dashboard";
import { jevIds, parseBrainAnswers } from "@/lib/jev";
import type { Controller } from "@/lib/types";
import "./ask-why.css";

const MAX = 300;

/** Ask the room's AI assistant why: the question goes to the integration (crop_steering.brain_ask) and the
 * controller answers it from the decision record on the room's answers sensor. Asking costs from the room's AI
 * budget, so only an administrator may; anyone sees the answers. */
export function AskWhy({ controller, zone }: { controller: Controller; zone?: number }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { room, states } = controller;
  const answers = parseBrainAnswers(states[jevIds(room.room.prefix).answers]);
  const locked = controller.admin === false;
  async function ask() {
    setBusy(true);
    setError("");
    try {
      await controller.operator("brain_ask", {
        question: question.trim(),
        ...(zone ? { zone } : {}),
      });
      setQuestion("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel ask-why" aria-label="Ask why">
      <form
        className="ask-why-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (question.trim() && !busy) void ask();
        }}
      >
        <Input
          aria-label="Question for the AI assistant"
          placeholder="Ask why…"
          maxLength={MAX}
          value={question}
          disabled={busy || locked}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <Button type="submit" disabled={busy || locked || !question.trim()}>
          Ask
        </Button>
        <UiTip copyKey="ask" />
      </form>
      <p className="muted small">
        {locked
          ? "Only an administrator can ask: each answer costs from the room’s AI budget."
          : `${question.length}/${MAX}. Answered from the AI assistant’s decision record, at most ${
              answers?.limit ?? 20
            } questions a day.`}
      </p>
      {error && (
        <p className="jev-trouble" role="alert">
          {error}
        </p>
      )}
      {!!answers?.pending && <p className="muted small">Asking…</p>}
      {!!answers?.answers.length && (
        <ol className="ask-why-list">
          {answers.answers.map((item) => (
            <li key={item.id} data-cannot={item.cannotAnswer || undefined}>
              <strong>{item.question}</strong>
              <span>{item.answer}</span>
              {item.answeredAt !== null && (
                <time className="muted small">{clock(item.answeredAt)}</time>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
