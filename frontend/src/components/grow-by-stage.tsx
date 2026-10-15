import { Pill } from "@/components/mini-visuals";
import { rangeText } from "@/lib/day-chart";
import { readJev } from "@/lib/jev";
import { NOMINAL_FLOWER_DAYS, stageArc, stageNow, weekOf } from "@/lib/stage-arc";
import type { Controller } from "@/lib/types";
import "./grow-by-stage.css";

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Plan › Schedule's first answer: what each stage of this flower asks for, where today is, and
 * what changes next and when. The arc is the one the controller's Jev steers by; today's flower day
 * is the one it reports. */
export function GrowByStage({ controller }: { controller: Controller }) {
  const stage = readJev(controller.states, controller.room.room.prefix).room?.stage ?? null;
  const length = stage?.days ?? NOMINAL_FLOWER_DAYS;
  const arc = stageArc(length);
  const today = stageNow(arc, stage?.day ?? null, Date.now());
  const weeks = Math.ceil(length / 7);
  return (
    <section className="panel grow-stages" aria-labelledby="grow-stages-title">
      <div className="panel-heading">
        <div>
          <h2 id="grow-stages-title">This flower by stage</h2>
          <p>
            {today
              ? `Flower day ${today.day} of ${length}, week ${today.week}: ${today.stage.name}, steered ${today.stage.steering}.`
              : "The controller reports no flower day for this room, so today is not marked on the arc."}
            {today?.next &&
              ` ${capital(today.next.stage.name)} from ${new Date(today.next.date).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} (day ${today.next.day}).`}
          </p>
        </div>
      </div>
      <ol className="grow-weeks" aria-label="Grow weeks by stage">
        {Array.from({ length: weeks }, (_, index) => {
          const week = index + 1;
          const first = index * 7 + 1;
          const owner = arc.find((item) => first >= item.first && first <= item.last);
          return (
            <li
              key={week}
              data-steering={owner?.steering}
              aria-current={today?.week === week ? "step" : undefined}
              title={owner ? `Week ${week}: ${owner.name}` : `Week ${week}`}
            >
              W{week}
            </li>
          );
        })}
      </ol>
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Stages of this flower">
        <table className="data-table grow-stage-table">
          <thead>
            <tr>
              <th scope="col">Stage</th>
              <th scope="col">Flower days</th>
              <th scope="col">Steering</th>
              <th scope="col">Pore EC</th>
              <th scope="col">Overnight dryback</th>
              <th scope="col">Runoff</th>
            </tr>
          </thead>
          <tbody>
            {arc.map((item) => {
              const current = today?.stage.name === item.name;
              return (
                <tr key={item.name} data-current={current || undefined}>
                  <th scope="row">
                    {capital(item.name)}
                    {current && (
                      <>
                        {" "}
                        <Pill tone="water">Now · week {today!.week}</Pill>
                      </>
                    )}
                    <small>Moves on when {item.moveOn}</small>
                  </th>
                  <td>
                    {item.first}–{item.last}
                    <small>
                      weeks {weekOf(item.first)}–{weekOf(item.last)}
                    </small>
                  </td>
                  <td data-steering={item.steering}>{capital(item.steering)}</td>
                  <td>{rangeText(item.poreEc)} mS/cm</td>
                  <td>
                    {rangeText(item.athena, 0)} % of peak
                    <small>{rangeText(item.drybackPoints, 0)} points of true water content</small>
                  </td>
                  <td>{rangeText(item.runoff, 0)} % of the feed</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted grow-stages-note">
        Day 1 is the first day of 12/12. Stages, pore EC and runoff are the guide Jev steers by; the
        dryback is Athena’s, relative to the day’s peak, the way the P3 dryback target is set. The
        grow plan below sets each zone’s targets day by day.
      </p>
    </section>
  );
}
