"""Dedicated worker entry point for ingestion, evaluation, and retention tasks."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import getSettings
from cortex.database import sessionFactory
from cortex.logging_config import configureLogging, getLogger
from cortex.services.jobs import DurableJobService, processJob
from cortex.services.model_provider import OllamaModelProvider

logger = getLogger("worker")


async def runWorker() -> None:
    """Run the durable worker loop until cancelled by the process supervisor."""
    configureLogging()
    settings = getSettings()
    logger.info("worker_started", queues=["ingestion", "evaluation", "retention"])
    try:
        while True:
            await runWorkerIteration(settings)
            await asyncio.sleep(settings.workerPollIntervalSeconds)
    except asyncio.CancelledError:
        logger.info("worker_stopped")


async def runWorkerIteration(settings) -> None:
    """Claim and execute at most one job to keep worker loops simple and observable."""
    async with sessionFactory() as session:
        await processNextJob(session, settings)


async def processNextJob(session: AsyncSession, settings) -> None:
    """Execute one claimed job and record either completion or failure."""
    modelProvider = OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )
    jobService = DurableJobService(session)
    jobRecord = await jobService.claimNextJob()
    if jobRecord is None:
        return
    try:
        await processJob(session, settings, modelProvider, jobRecord)
        await jobService.completeJob(jobRecord.id)
        logger.info("job_completed", jobId=str(jobRecord.id), jobType=jobRecord.jobType)
    except Exception as error:
        await jobService.failJob(jobRecord.id, str(error))
        logger.error(
            "job_failed",
            jobId=str(jobRecord.id),
            jobType=jobRecord.jobType,
            error=str(error),
        )
        raise


def main() -> None:
    """Start the worker process from a module or container command."""
    asyncio.run(runWorker())


if __name__ == "__main__":
    main()
