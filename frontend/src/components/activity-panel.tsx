import { useState } from "react";
import { Activity, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { EventList } from "@/components/dashboard";
import type { Controller } from "@/lib/types";

/** The room's latest controller records beside any page, closed until asked for. */
export function ActivityPanel({
  controller,
  openLog,
}: {
  controller: Controller;
  openLog: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {/* The trigger gets focus back when the panel closes and announces open or closed. */}
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Recent activity" title="Recent activity">
          <Activity size={17} />
        </Button>
      </SheetTrigger>
      <SheetContent className="activity-sheet">
        <SheetHeader>
          <SheetTitle>Recent activity</SheetTitle>
          <SheetDescription>{controller.room.room.name}</SheetDescription>
        </SheetHeader>
        <div
          className="activity-sheet-list"
          tabIndex={0}
          role="region"
          aria-label="Latest controller records"
        >
          <EventList events={controller.room.events.slice(0, 10)} />
        </div>
        <SheetFooter>
          <Button
            variant="outline"
            onClick={() => {
              setOpen(false);
              openLog();
            }}
          >
            Open the activity log <ArrowRight size={16} />
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
