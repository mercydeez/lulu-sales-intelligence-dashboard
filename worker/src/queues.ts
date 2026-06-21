/**
 * Queue registry + enqueue helper (worker side).
 *
 * Queue names MUST match backend/app/services/queue.py. Default job options
 * mirror the producer's (exponential backoff, capped retries, keep recent
 * completed/failed for observability).
 */
import { Queue, JobsOptions } from "bullmq";
import { connection } from "./redis";

// Keep in sync with backend/app/services/queue.py
export const Q_WEBHOOK = "webhook";
export const Q_RISK_SCAN = "risk-scan";
export const Q_REPORT = "report";
export const Q_DIGEST = "digest";

export const DEFAULT_JOB_OPTS: JobsOptions = {
  attempts: 5,
  backoff: { type: "exponential", delay: 2000 },
  removeOnComplete: 1000,
  removeOnFail: 5000,
};

const queues: Record<string, Queue> = {};

export function getQueue(name: string): Queue {
  if (!queues[name]) {
    queues[name] = new Queue(name, { connection });
  }
  return queues[name];
}

export async function enqueue(
  name: string,
  jobName: string,
  data: unknown,
  opts?: JobsOptions,
) {
  return getQueue(name).add(jobName, data, opts ?? DEFAULT_JOB_OPTS);
}

export async function closeQueues(): Promise<void> {
  await Promise.all(Object.values(queues).map((q) => q.close()));
}
