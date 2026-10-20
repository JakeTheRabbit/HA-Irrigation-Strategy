import { StockDemo } from "./stock-demo";
import { expect, it } from "vitest";
import { stockConfigurationPayload, type StockTankDraft } from "./stock";
const draft: StockTankDraft = {
  id: "a",
  name: "A",
  capacity_l: 20,
  level_l: 15,
  low_l: 1,
  dose_ml: 25,
  dose_entity: null,
};
it("existing tank configuration omits cached current level, preserving newer draws and refills", () => {
  const [payload] = stockConfigurationPayload([draft]);
  expect(payload).not.toHaveProperty("level_l");
  expect(payload).toMatchObject({ id: "a", capacity_l: 20, dose_ml: 25 });
  expect(draft.level_l).toBe(15);
});
it("new tanks retain initial fill level", () => {
  const { id: _id, ...initial } = draft;
  expect(stockConfigurationPayload([initial])[0]).toHaveProperty("level_l", 15);
});

it("demo follows controller omission semantics after a newer measured level", () => {
  const store = new StockDemo(() => ({}));
  const doc = store.call("stock_get", { room_id: "room:" });
  const tank = doc.tanks[0];
  const changed = store.call("stock_refill", {
    room_id: doc.room_id,
    expected_revision: doc.revision,
    id: tank.id,
    level_l: 3,
  });
  const saved = store.call("stock_save", {
    room_id: doc.room_id,
    expected_revision: changed.revision,
    tanks: stockConfigurationPayload(
      doc.tanks.map((t) => ({ ...t, name: t.id === tank.id ? "Renamed" : t.name })),
    ),
  });
  expect(saved.tanks.find((t) => t.id === tank.id)?.level_l).toBe(3);
});
