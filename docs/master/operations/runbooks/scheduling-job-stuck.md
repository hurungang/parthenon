# Runbook: Scheduling Job Stuck

## Symptoms

- A scheduled job appears as triggered in Scheduling Engine logs but never reaches a completed state
- The scheduler queue depth is growing continuously
- The downstream agent run that the job was expected to trigger is missing from agent execution logs
- The job's status record in the database shows `running` well beyond its expected execution duration

---

## Resolution Steps

1. Check the Scheduling Engine logs for the specific job's `trigger` event. Confirm the log shows the job was dispatched to the Agent Engine with the correct agent type ID and prompt payload. If the trigger log entry is missing, the APScheduler job may have fired but failed to execute the dispatch function — check the Scheduling Engine for unhandled exceptions around the trigger time.

2. Check the Agent Engine logs for the corresponding instance creation event. The log should contain an `instance created` entry with a reference back to the scheduled job's trigger. If this entry is missing, the dispatch call from the Scheduling Engine to the Agent Engine failed — check network connectivity between the two services and confirm the Agent Engine health endpoint is responding.

3. If the instance was created in the Agent Engine but the job never completed, treat the agent instance as stuck and follow the agent instance limit runbook to identify and force-close the orphaned instance. Once the instance is closed, the job should be able to complete or be manually re-triggered.

4. Check the persistent job store in PostgreSQL. Query the `scheduled_jobs` and `job_executions` tables for the affected job ID. A `job_executions` record with status `running` and a start time well in the past (beyond the expected job duration) confirms the job is stuck mid-execution rather than simply slow. A missing `job_executions` record means the execution never started despite the trigger event.

5. Reset the job's execution state in the job store by updating the stuck `job_executions` record status to `failed` with an appropriate error note. Then re-trigger the job manually from the admin UI to create a fresh execution. Monitor the new execution through to completion before re-enabling the recurring schedule.

---

## Notes

- Before re-enabling a fixed schedule, investigate and resolve the root cause — a recurring stuck job will continue to backlog the queue
- If multiple jobs are stuck simultaneously, the issue is more likely in the Agent Engine (instance limit reached, service crash) than in the Scheduling Engine — check the Agent Engine health first
- The PostgreSQL job store state is the authoritative source for job execution status; APScheduler's in-memory state is secondary and may diverge after a service restart
