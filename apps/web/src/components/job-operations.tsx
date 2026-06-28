/** Durable job operations panel for developer-side ingestion visibility. */

import { useEffect, useState } from "react";
import { ArrowsLeftRight, Clock, WarningCircle } from "@phosphor-icons/react";
import { getJobs, getJobStatus } from "../lib/api-client";
import type { JobStatus, JobSummary } from "../types";

interface JobOperationsProps {
  enterpriseId: string;
  highlightedJobId: string | null;
}

/** Render the newest persisted worker jobs with their status and failure detail. */
export function JobOperations({ enterpriseId, highlightedJobId }: JobOperationsProps) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(highlightedJobId);
  const [selectedJob, setSelectedJob] = useState<JobStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const queuedCount = jobs.filter((job) => job.status === "queued").length;
  const runningCount = jobs.filter((job) => job.status === "running").length;
  const failedCount = jobs.filter((job) => job.status === "failed").length;
  const completedCount = jobs.filter((job) => job.status === "completed").length;
  const attentionJob = jobs.find((job) => job.status === "failed") ?? jobs.find((job) => job.status === "running") ?? null;

  useEffect(() => {
    let isMounted = true;

    async function loadJobs(): Promise<void> {
      try {
        const liveJobs = await getJobs(enterpriseId);
        if (isMounted) {
          setJobs(liveJobs);
          setSelectedJobId((currentSelectedJobId) => {
            if (highlightedJobId && liveJobs.some((job) => job.jobId === highlightedJobId)) {
              return highlightedJobId;
            }
            if (currentSelectedJobId && liveJobs.some((job) => job.jobId === currentSelectedJobId)) {
              return currentSelectedJobId;
            }
            return liveJobs[0]?.jobId ?? null;
          });
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

  useEffect(() => {
    let isMounted = true;
    if (!selectedJobId) {
      setSelectedJob(null);
      return;
    }
    const jobId = selectedJobId;

    async function loadJobDetail(): Promise<void> {
      try {
        const jobDetail = await getJobStatus(jobId);
        if (isMounted) {
          setSelectedJob(jobDetail);
          setErrorMessage(null);
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "Failed to load job detail");
        }
      }
    }

    void loadJobDetail();
    const pollTimer = window.setInterval(() => {
      void loadJobDetail();
    }, 4000);
    return () => {
      isMounted = false;
      window.clearInterval(pollTimer);
    };
  }, [selectedJobId]);

  return (
    <section className="job-operations">
      <div className="section-heading">
        <ArrowsLeftRight aria-hidden size={18} />
        <strong>Durable jobs</strong>
        <span>{jobs.length}</span>
      </div>
      <div className="metric-strip" style={{ marginBottom: 16 }}>
        <span><small>Queued</small><strong>{queuedCount}</strong></span>
        <span><small>Running</small><strong>{runningCount}</strong></span>
        <span><small>Completed</small><strong>{completedCount}</strong></span>
        <span><small>Failed</small><strong>{failedCount}</strong></span>
      </div>
      {attentionJob ? (
        <div className="query-error" role="alert" style={{ marginBottom: 16 }}>
          <WarningCircle aria-hidden size={18} />
          <div>
            <strong>Operator attention</strong>
            <span>
              {attentionJob.status === "failed"
                ? `Job ${attentionJob.jobId.slice(0, 8)} failed${attentionJob.lastError ? `: ${attentionJob.lastError}` : "."}`
                : `Job ${attentionJob.jobId.slice(0, 8)} is still running. Check lock time and source detail if throughput stalls.`}
            </span>
          </div>
        </div>
      ) : null}
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
                className={selectedJobId === job.jobId ? "job-row job-row--highlighted" : "job-row"}
                onClick={() => setSelectedJobId(job.jobId)}
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
      <div className="source-form-card" style={{ marginTop: 16 }}>
        <div className="source-form-card__heading">
          <Clock aria-hidden size={18} />
          <strong>{selectedJob ? "Selected job detail" : "Job detail"}</strong>
        </div>
        {selectedJob ? (
          <>
            <p>
              <strong>{selectedJob.jobType}</strong> · {selectedJob.status} · attempts {selectedJob.attempts}
            </p>
            <dl className="source-detail__facts">
              <div><dt>Available</dt><dd>{new Date(selectedJob.availableAt).toLocaleString()}</dd></div>
              <div><dt>Locked</dt><dd>{selectedJob.lockedAt ? new Date(selectedJob.lockedAt).toLocaleString() : "not locked"}</dd></div>
              <div><dt>Updated</dt><dd>{new Date(selectedJob.updatedAt).toLocaleString()}</dd></div>
              <div><dt>Document</dt><dd>{selectedJob.documentId ?? "—"}</dd></div>
              <div><dt>Version</dt><dd>{selectedJob.documentVersionId ?? "—"}</dd></div>
              <div><dt>Source</dt><dd>{selectedJob.sourceDisplayName ?? "—"}</dd></div>
              <div><dt>Last error</dt><dd>{selectedJob.lastError ?? "none"}</dd></div>
            </dl>
          </>
        ) : (
          <div className="empty-tab">
            <Clock aria-hidden size={24} />
            <p>Select a job to inspect its latest persisted state.</p>
          </div>
        )}
      </div>
    </section>
  );
}
