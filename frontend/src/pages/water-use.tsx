import { Empty, Heading } from "@/components/dashboard";
import { DailyWaterSummary } from "@/components/water-delivery";
import { WaterUsePanel } from "@/components/water-use";
import type { Controller } from "@/lib/types";

/** History › Water use: each zone's litres today, this grow week and since the grow began, the
 * estimate for the whole grow and litres per grow week; then this grow-day's water per plant. */
export function WaterUsePage({ controller }: { controller: Controller }) {
  const { zones } = controller.room;
  return (
    <>
      <Heading title="Water use" />
      {zones.length ? (
        <>
          <WaterUsePanel controller={controller} zones={zones} title="Litres by zone" />
          <DailyWaterSummary controller={controller} zones={zones} />
        </>
      ) : (
        <section className="panel">
          <Empty
            title="No zones discovered"
            detail="Water use appears once the room’s zones are configured and report their water."
          />
        </section>
      )}
    </>
  );
}
