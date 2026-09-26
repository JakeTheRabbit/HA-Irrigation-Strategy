import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Controller } from "@/lib/types";
import {
  compareVersions,
  readWhatsNew,
  recent,
  releaseUrl,
  RELEASES_URL,
  unseen,
  type WhatsNewSelection,
} from "@/lib/whats-new";
import "./whats-new.css";

const day = (date: string) =>
  new Date(`${date}T12:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

/** The release highlights, newest first, with the full release notes a link away. */
export function WhatsNewDialog({
  selection,
  onClose,
  description,
}: {
  selection: WhatsNewSelection;
  onClose: () => void;
  description: string;
}) {
  const newest = selection.releases[0];
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="whats-new" data-whats-new>
        <DialogHeader>
          <DialogTitle>
            <Sparkles size={18} aria-hidden="true" /> What’s new in Crop Steering
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {/* Focusable, so a keyboard can scroll it where it does not fit. */}
        <div className="whats-new-releases" role="region" aria-label="Highlights" tabIndex={0}>
          {selection.releases.map((release) => (
            <section key={release.version} aria-labelledby={`whats-new-${release.version}`}>
              <h3 id={`whats-new-${release.version}`}>
                Version {release.version}
                <span>{day(release.date)}</span>
              </h3>
              <ul>
                {release.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
          {selection.more > 0 && (
            <p className="whats-new-more">
              And {selection.more} earlier {selection.more === 1 ? "release" : "releases"}, in{" "}
              <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
                the release notes
              </a>
              .
            </p>
          )}
        </div>
        <div className="whats-new-actions">
          {newest && (
            <a
              className="whats-new-notes"
              href={releaseUrl(newest.version)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Full release notes <ArrowUpRight size={15} aria-hidden="true" />
            </a>
          )}
          <Button onClick={onClose}>Got it</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const connected = (controller: Controller) =>
  controller.connection === "live" || controller.connection === "demo";

/** Once, the first time anyone opens the dashboard after an update: what changed since the window
 * last showed on this installation. It says so for everyone as it opens, so the next person, or
 * the next page load, does not see it again. An integration without What's new shows nothing. */
export function WhatsNewOnUpdate({ controller }: { controller: Controller }) {
  const [selection, setSelection] = useState<WhatsNewSelection | null>(null);
  const asked = useRef(false);
  const ready = connected(controller);
  const { operator } = controller;
  useEffect(() => {
    if (!ready || asked.current) return;
    asked.current = true;
    void (async () => {
      const doc = readWhatsNew(await operator("whats_new_get").catch(() => null));
      if (!doc || (doc.seen !== null && compareVersions(doc.seen, doc.version) >= 0)) return;
      const found = unseen(doc);
      if (found.releases.length) setSelection(found);
      await operator("whats_new_seen", { version: doc.version }).catch(() => null);
    })();
  }, [ready, operator]);
  return (
    selection && (
      <WhatsNewDialog
        selection={selection}
        onClose={() => setSelection(null)}
        description="The main changes since this dashboard last showed them. The release notes have every detail."
      />
    )
  );
}

/** Help & tools: the latest releases' highlights, at any time. */
export function WhatsNewButton({ controller }: { controller: Controller }) {
  const [selection, setSelection] = useState<WhatsNewSelection | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    setError(null);
    const doc = readWhatsNew(await controller.operator("whats_new_get").catch(() => null));
    if (doc?.releases.length) setSelection(recent(doc));
    else setError("What’s new needs the updated Crop Steering integration.");
  }
  return (
    <div className="whats-new-button">
      <Button variant="outline" disabled={!connected(controller)} onClick={() => void open()}>
        <Sparkles size={16} aria-hidden="true" /> What’s new
      </Button>
      {error && (
        <p className="small muted" role="status">
          {error}
        </p>
      )}
      {selection && (
        <WhatsNewDialog
          selection={selection}
          onClose={() => setSelection(null)}
          description="The latest releases, in short. The release notes have every detail."
        />
      )}
    </div>
  );
}
