export function calculateDryback(start, end) {
  start = Number(start);
  end = Number(end);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start <= 0 ||
    start > 100 ||
    end < 0 ||
    end > start
  )
    throw Error(
      "Use a starting VWC above zero and an ending VWC between zero and the starting value.",
    );
  return {
    points: Number((start - end).toFixed(10)),
    relative: Number((((start - end) / start) * 100).toFixed(10)),
  };
}
export function calculateFlow({
  litersPerHour,
  drippersPerPlant,
  seconds,
  plants,
}) {
  const values = [litersPerHour, drippersPerPlant, seconds, plants].map(Number);
  if (
    values.some((v) => !Number.isFinite(v) || v <= 0) ||
    !Number.isInteger(values[1]) ||
    !Number.isInteger(values[3])
  )
    throw Error(
      "Enter positive measured flow and runtime. Drippers and plant count must be whole numbers.",
    );
  const perPlant = (values[0] * values[1] * values[2]) / 3600;
  const zone = perPlant * values[3];
  if (!Number.isFinite(perPlant) || !Number.isFinite(zone))
    throw Error(
      "These inputs are too large. Use realistic flow, runtime and plant counts.",
    );
  return {
    perPlant,
    zone,
    basis: "Runtime estimate; not measured plant uptake.",
  };
}
export function planningPreview(floor, actual) {
  floor = Number(floor);
  if (!Number.isFinite(floor) || floor < 0 || floor > 100)
    throw Error("The example threshold must be between 0 and 100% VWC.");
  return { floor, actual };
}
export function gradeQuiz(quiz, selected) {
  const feedback = quiz.map((q) => {
    const index = selected[q.id],
      option = Number.isInteger(index) ? q.options[index] : null;
    return {
      id: q.id,
      correct: option?.correct === true,
      message:
        option?.feedback || "Choose an answer before you check this question.",
      critical: q.safetyCritical === true,
    };
  });
  const correct = feedback.filter((x) => x.correct).length,
    percent = quiz.length ? Math.round((correct / quiz.length) * 100) : 0;
  return {
    percent,
    correct,
    total: quiz.length,
    passed: percent >= 80 && feedback.every((x) => !x.critical || x.correct),
    feedback,
  };
}
