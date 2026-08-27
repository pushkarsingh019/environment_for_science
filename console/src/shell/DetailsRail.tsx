import type { ReactNode } from "react";

export interface RailSection {
  id: string;
  title: string;
  node: ReactNode;
}

export interface DetailsRailProps {
  open: boolean;
  sections: RailSection[];
}

/** Sticky, scrollable right rail; carries the `hidden` attribute when closed. */
export function DetailsRail(props: DetailsRailProps): JSX.Element {
  const { open, sections } = props;

  return (
    <aside className="details-rail" aria-label="Environment and run details" hidden={!open}>
      {sections.map((section) => {
        const titleId = `rail-${section.id}-title`;
        return (
          <section key={section.id} className="rail-section" id={`rail-${section.id}`} aria-labelledby={titleId}>
            <p className="eyebrow" id={titleId}>
              {section.title}
            </p>
            {section.node}
          </section>
        );
      })}
    </aside>
  );
}
