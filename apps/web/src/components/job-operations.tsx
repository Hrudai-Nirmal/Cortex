/** Durable job operations panel for developer-side ingestion visibility. */

import { useEffect, useState } from "react";
import { ArrowsLeftRight, Clock, WarningCircle } from "@phosphor-icons/react";
import { getJobs } from "../lib/api-client";
import type { JobSummary } from "../types";

interface JobOperationsProps {
  enterpriseId: string;
  highlightedJobId: string | null;
}

/** Render the newest persisted worker jobs with their status and failure detail. */
export function JobOperations({ enterpriseId, highlightedJobId }: JobOperationsProps) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadJobs(): Promise<void> {
      try {
        const liveJobs = await getJobs(enterpriseId);
        if (isMounted) {
          setJobs(liveJobs);
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to load jobs");
        }
      }
    }

    void loadJobs();
    const pollTimer = window.setInterval(() => {
      void loadJobs();
    }, 4000);
    return () => {
      isMounted = false;
      window.clearInterval(pollTimer);
    };
  }, [enterpriseId, highlightedJobId]);

  return (
    <section className="job-operations">
      <div className="section-heading">
        <ArrowsLeftRight aria-hidden size={18} />
        <strong>Durable jobs</strong>
        <span>{jobs.length}</span>
      </div>
      {errorMessage ? (
        <div className="query-error" role="alert">
          <WarningCircle aria-hidden size={18} />
          <div>
            <strong>Jobs warning</strong>
            <span>{errorMessage}</span>
          </div>
        </div>
      ) : null}
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Status</th>
            <th>Type</th>
            <th>Attempts</th>
            <th>Source</th>
            <th>Updated</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {jobs.length > 0 ? (
            jobs.map((job) => (
              <tr
                key={job.jobId}
                className={highlightedJobId === job.jobId ? "job-row job-row--highlighted" : "job-row"}
              >
                <td><code>{job.jobId.slice(0, 8)}</code></td>
                <td>{job.status}</td>
                <td>{job.jobType}</td>
                <td>{job.attempts}</td>
                <td>{job.sourceDisplayName ?? "—"}</td>
                <td>{new Date(job.updatedAt).toLocaleTimeString()}</td>
                <td>{job.lastError ?? "—"}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={7}>
                <div className="empty-tab">
                  <Clock aria-hidden size={24} />
                  <p>No durable jobs yet.</p>
                </div>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
