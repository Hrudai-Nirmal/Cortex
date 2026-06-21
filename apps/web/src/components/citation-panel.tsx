/** Friendly source list reveals provenance without exposing internal pipeline mechanics. */

import { ArrowSquareOut, CheckCircle } from "@phosphor-icons/react";
import type { Citation } from "../types";

interface CitationPanelProps {
  citations: Citation[];
}

/** Render exact supporting spans for an employee answer. */
export function CitationPanel({ citations }: CitationPanelProps) {
  if (citations.length === 0) {
    return null;
  }
  return (
    <section className="citation-panel" aria-label="Sources">
      <h3>Sources</h3>
      {citations.map((citation) => (
        <article className="citation-item" key={citation.citationId}>
          <div className="citation-item__heading">
            <span className="citation-index">{citation.citationId.replace("C", "")}</span>
            <div><strong>{citation.documentTitle}</strong><span>Version {citation.documentVersion}</span></div>
            <CheckCircle aria-label="Supported" size={18} weight="fill" />
          </div>
          <blockquote>{citation.exactSpan}</blockquote>
          <div className="citation-item__meta"><span>{citation.structuralLocator}</span><span>{Math.round(citation.supportScore * 100)}% support</span><ArrowSquareOut aria-hidden size={15} /></div>
        </article>
      ))}
    </section>
  );
}
