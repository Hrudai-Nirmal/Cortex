"""Dedicated worker entry point for ingestion, evaluation, and retention tasks."""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings, getSettings
from cortex.database import sessionFactory
from cortex.errors import WorkerStartupError
from cortex.logging_config import configureLogging, getLogger
from cortex.schemas import RuntimeComponentSchema, RuntimeHealthResponse
from cortex.services.jobs import DurableJobService, processJob
from cortex.services.model_provider import OllamaModelProvider
from cortex.services.runtime import RuntimeHealthService

logger = getLogger("worker")


async def runWorker() -> None:
    """Run the durable worker loop until cancelled by the process supervisor."""
    configureLogging()
    settings = getSettings()
    await validateWorkerStartup(settings)
    logger.info("worker_started", queues=["ingestion", "evaluation", "retention"])
    try:
        while True:
            await runWorkerIteration(settings)
            await asyncio.sleep(settings.workerPollIntervalSeconds)
    except asyncio.CancelledError:
        logger.info("worker_stopped")


async def validateWorkerStartup(settings: Settings) -> None:
    """Fail fast when the worker runtime is not safe to enter its polling loop."""
    modelProvider = OllamaModelProvider(
        baseUrl=settings.ollamaBaseUrl,
        generatorModel=settings.generatorModel,
        embeddingModel=settings.embeddingModel,
    )
    staticHealth = await RuntimeHealthService(
        session=None,
        settings=settings,
        modelProvider=modelProvider,
    ).getStartupReadiness()
    logRuntimeHealth("worker_startup_static_health", staticHealth)
    staticFailures = RuntimeHealthService.getFailingComponents(staticHealth)
    if staticFailures:
        logger.error(
            "worker_startup_blocked",
            phase="startup",
            components=serializeRuntimeComponents(staticFailures),
        )
        raise WorkerStartupError(
            buildStartupFailureMessage(staticFailures)
        )

    try:
        async with sessionFactory() as session:
            liveHealth = await RuntimeHealthService(
                session=session,
                settings=settings,
                modelProvider=modelProvider,
            ).getReadiness()
    except Exception as error:
        logger.error("worker_startup_health_error", error=str(error))
        raise WorkerStartupError(
            buildStartupExceptionMessage(
                "worker startup could not verify live runtime readiness",
                error,
            )
        ) from error

    logRuntimeHealth("worker_startup_live_health", liveHealth)
    liveFailures = RuntimeHealthService.getFailingComponents(liveHealth)
    if liveFailures:
        logger.error(
            "worker_startup_blocked",
            phase="live",
            components=serializeRuntimeComponents(liveFailures),
        )
        raise WorkerStartupError(
            buildStartupFailureMessage(liveFailures)
        )


def logRuntimeHealth(eventName: str, runtimeHealth: RuntimeHealthResponse) -> None:
    """Emit one structured health event without leaking trace or document content."""
    logger.info(
        eventName,
        status=runtimeHealth.status,
        environment=runtimeHealth.environment,
        components=serializeRuntimeComponents(runtimeHealth.components),
    )


def serializeRuntimeComponents(
    runtimeComponents: list[RuntimeComponentSchema],
) -> list[dict[str, str | None]]:
    """Convert runtime-health components into stable structured-log dictionaries."""
    return [
        {
            "name": component.name,
            "status": component.status,
            "severity": component.severity,
            "detail": component.detail,
            "remediation": component.remediation,
        }
        for component in runtimeComponents
    ]


def buildStartupFailureMessage(
    failingComponents: list[RuntimeComponentSchema],
) -> str:
    """Collapse failing runtime components into one operator-readable startup error."""
    formattedFailures = []
    for component in failingComponents:
        if component.remediation:
            formattedFailures.append(
                f"{component.name}: {component.detail} | remediation: {component.remediation}"
            )
        else:
            formattedFailures.append(f"{component.name}: {component.detail}")
    return "worker startup blocked by runtime health checks: " + "; ".join(formattedFailures)


def buildStartupExceptionMessage(prefix: str, error: Exception) -> str:
    """Preserve the underlying startup exception text for operator troubleshooting."""
    normalizedDetail = str(error).strip() or error.__class__.__name__
    return f"{prefix}: {normalizedDetail}"


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
    argumentParser = argparse.ArgumentParser(description="Run the Cortex durable worker.")
    argumentParser.add_argument(
        "--check-startup",
        action="store_true",
        help="Validate worker startup health and exit without entering the job loop.",
    )
    arguments = argumentParser.parse_args()
    configureLogging()
    settings = getSettings()
    if arguments.check_startup:
        asyncio.run(validateWorkerStartup(settings))
        logger.info("worker_startup_check_passed")
        return
    asyncio.run(runWorker())


if __name__ == "__main__":
    main()
