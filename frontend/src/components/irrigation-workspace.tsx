import type { ReactNode } from "react";
import { Heading } from "@/components/dashboard";

/** Embedded editors contribute their existing actions without another page heading. */
export function WorkspaceHeading({
  embedded,
  title,
  description,
  action,
}: {
  embedded?: boolean;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  if (!embedded) return <Heading title={title} description={description} action={action} />;
  return (
    <div className="irrigation-editor-actions" aria-label={`${title} actions`}>
      {description && <p className="muted small">{description}</p>}
      {action}
    </div>
  );
}
