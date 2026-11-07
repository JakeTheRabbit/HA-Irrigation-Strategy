import { TriangleAlert } from "lucide-react";
import type { roomAttention } from "@/lib/facility-view";
import "./needs-attention.css";

/** One line under a room's heading: what needs a look, each a link to where it is fixed. Nothing
 * when all is well, so a calm room stays calm. */
export function NeedsAttention({
  items,
  open,
}: {
  items: ReturnType<typeof roomAttention>;
  open: (item: ReturnType<typeof roomAttention>[number]) => void;
}) {
  if (!items.length) return null;
  return (
    <p className="needs-attention" data-needs-attention>
      <TriangleAlert size={15} aria-hidden="true" />
      <strong>Needs attention</strong>
      {items.map((item) => (
        <button key={item.key} type="button" className="inline-action" onClick={() => open(item)}>
          {item.text}
        </button>
      ))}
    </p>
  );
}
