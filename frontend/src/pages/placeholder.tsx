import { Empty, Heading } from "@/components/dashboard";
import type { Page } from "@/lib/routes";
import type { Controller } from "@/lib/types";

/** The props every page gets from the app shell. */
export interface PageProps {
  controller: Controller;
  navigate: (page: Page) => void;
  onDirtyChange: (dirty: boolean) => void;
}

/** A page that has its address and menu entry but not its content yet. */
export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <Heading title={title} />
      <section className="panel" data-placeholder-page>
        <Empty title="Coming in this release" detail="This page is not built yet." />
      </section>
    </>
  );
}
