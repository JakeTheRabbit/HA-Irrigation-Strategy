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
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Recent activity"
        title="Recent activity"
        onClick={() => setOpen(true)}
      >
        <Activity size={17} />
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="activity-sheet">
          <SheetHeader>
            <SheetTitle>Recent activity</SheetTitle>
            <SheetDescription>{controller.room.room.name}</SheetDescription>
          </SheetHeader>
          <div className="activity-sheet-list">
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
    </>
  );
}
