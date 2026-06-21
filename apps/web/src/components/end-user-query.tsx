/** Focused employee query surface intentionally hides developer pipeline internals. */

import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpenText,
  CheckCircle,
  Copy,
  Info,
  SpinnerGap,
  ThumbsDown,
  ThumbsUp,
} from "@phosphor-icons/react";
import { getSession, submitChatQuery } from "../lib/api-client";
import type { QueryResponse, Session } from "../types";
import { CitationPanel } from "./citation-panel";

const suggestions = [
  "What are our data retention rules?",
  "How is document access enforced?",
  "What must pass before a pipeline is promoted?",
];

/** Render a calm ask-answer-feedback experience for enterprise employees. */
export function EndUserQuery() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showCitations, setShowCitations] = useState(true);
  const [feedback, setFeedback] = useState<"helpful" | "unhelpful" | null>(null);
  const [isCopied, setIsCopied] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadSession(): Promise<void> {
      try {
        const resolvedSession = await getSession();
        if (isMounted) {
          setSession(resolvedSession);
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "Cortex could not load your session");
        }
      }
    }

    void loadSession();
    return () => {
      isMounted = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2 || isLoading || !session) {
      return;
    }
    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setIsLoading(true);
    setErrorMessage(null);
    setFeedback(null);
    try {
      const queryResponse = await submitChatQuery(
        normalizedQuery,
        showCitations,
        abortController.signal,
      );
      setResponse(queryResponse);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setErrorMessage(error instanceof Error ? error.message : "Cortex could not complete the query");
      }
    } finally {
      if (abortControllerRef.current === abortController) {
        setIsLoading(false);
      }
    }
  }

  function applySuggestion(suggestion: string): void {
    setQuery(suggestion);
  }

  async function handleCopy(): Promise<void> {
    if (!response) {
      return;
    }
    try {
      await navigator.clipboard.writeText(response.answer);
      setIsCopied(true);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "The answer could not be copied");
    }
  }

  return (
    <main className="query-surface">
      <header className="query-header">
        <div><span className="query-header__eyebrow">Enterprise knowledge</span><strong>Ask Cortex</strong></div>
        <label className="citation-toggle"><span>Show citations</span><input type="checkbox" checked={showCitations} onChange={(event) => setShowCitations(event.target.checked)} /><i aria-hidden /></label>
      </header>
      <section className={`query-content${response ? " query-content--answered" : ""}`}>
        {!response && !isLoading ? (
          <div className="query-welcome">
            <span className="welcome-mark"><BookOpenText aria-hidden size={28} weight="duotone" /></span>
            <h1>What would you like to know?</h1>
            <p>I’ll answer from information you’re allowed to access and show exactly where it came from.</p>
            <div className="suggestion-list">{suggestions.map((suggestion) => <button key={suggestion} type="button" onClick={() => applySuggestion(suggestion)}>{suggestion}</button>)}</div>
          </div>
        ) : null}
        {isLoading ? (
          <div className="query-loading" role="status"><SpinnerGap aria-hidden size={26} /><strong>Checking your authorized sources</strong><span>Retrieving, ranking, and validating evidence…</span></div>
        ) : null}
        {errorMessage ? <div className="query-error" role="alert"><Info aria-hidden size={20} /><div><strong>Cortex couldn’t answer</strong><span>{errorMessage}</span></div></div> : null}
        {response && !isLoading ? (
          <div className="answer-layout">
            <article className="answer-card">
              <div className="answer-status"><CheckCircle aria-hidden size={18} weight="fill" /><span>Supported by authorized sources</span></div>
              <h2>Answer</h2>
              <div className="answer-copy">
                {response.claims.length > 0 ? response.claims.map((claim) => <p key={claim.claimId}>{claim.text}{showCitations ? claim.citationIds.map((citationId) => <sup key={citationId}>{citationId.replace("C", "")}</sup>) : null}</p>) : <p>{response.answer}</p>}
              </div>
              <div className="answer-actions">
                <button type="button" aria-pressed={feedback === "helpful"} onClick={() => setFeedback("helpful")}><ThumbsUp aria-hidden size={17} weight={feedback === "helpful" ? "fill" : "regular"} /> Helpful</button>
                <button type="button" aria-pressed={feedback === "unhelpful"} onClick={() => setFeedback("unhelpful")}><ThumbsDown aria-hidden size={17} weight={feedback === "unhelpful" ? "fill" : "regular"} /> Needs work</button>
                <button type="button" onClick={handleCopy}><Copy aria-hidden size={17} /> {isCopied ? "Copied" : "Copy"}</button>
                {feedback ? <span className="feedback-thanks">Thanks for the feedback</span> : null}
              </div>
              <div className="answer-footnote"><Info aria-hidden size={15} /> Cortex only answered claims that passed evidence validation. Trace {response.traceId.slice(0, 8)}.</div>
            </article>
            {showCitations ? <CitationPanel citations={response.citations} /> : null}
          </div>
        ) : null}
      </section>
      <form className="query-composer" onSubmit={handleSubmit}>
        <textarea aria-label="Ask a question" placeholder="Ask about company knowledge…" value={query} onChange={(event) => setQuery(event.target.value)} rows={2} />
        <div className="query-composer__footer"><span>{session ? "Your access permissions are applied automatically." : "Loading your access scope…"}</span><button type="submit" disabled={query.trim().length < 2 || isLoading || !session} aria-label="Submit question"><ArrowUp aria-hidden size={19} weight="bold" /></button></div>
      </form>
    </main>
  );
}
