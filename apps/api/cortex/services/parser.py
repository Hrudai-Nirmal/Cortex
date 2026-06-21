"""Offline document parser adapters with explicit hardware and remote-service controls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cortex.config import Settings
from cortex.errors import HardwareAccelerationError, InputValidationError, ProviderOperationError
from cortex.services.accelerator import (
    AcceleratorReport,
    detectAvailableAccelerator,
    enforceAcceleratorBinding,
)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Return normalized parser output and device diagnostics without hiding failures."""

    content: str
    parserName: str
    parserVersion: str
    acceleratorReports: tuple[AcceleratorReport, ...]


class DocumentParser(Protocol):
    """Define the replaceable parser contract used by ingestion workers."""

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Parse one validated local file into normalized structured text."""
        ...


class PlainTextParser:
    """Parse UTF-8 text fixtures without invoking OCR or remote providers."""

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Read a non-empty text document asynchronously."""
        if not await asyncio.to_thread(filePath.is_file):
            raise InputValidationError(f"file does not exist: {filePath}")
        try:
            content = await asyncio.to_thread(filePath.read_text, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProviderOperationError(
                f"failed to read text document: {filePath.name}"
            ) from error
        if not content.strip():
            raise InputValidationError("parsed document cannot be empty")
        return ParsedDocument(
            content=content,
            parserName="plain-text",
            parserVersion="1.0.0",
            acceleratorReports=(),
        )


class DoclingParser:
    """Run Docling offline and enforce the deployment profile's accelerator requirement."""

    def __init__(self, settings: Settings) -> None:
        if settings is None:
            raise ValueError("settings are required")
        self.settings = settings

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Convert a supported document without allowing remote model services."""
        if not await asyncio.to_thread(filePath.is_file):
            raise InputValidationError(f"file does not exist: {filePath}")
        actualDevice = detectAvailableAccelerator()
        acceleratorReport = enforceAcceleratorBinding(
            stageName="docling-layout-table-ocr",
            requiredDevice=self.settings.requiredAccelerator,
            actualDevice=actualDevice,
            isStrict=self.settings.devMode,
        )
        try:
            parsedContent = await asyncio.to_thread(self._convertFile, filePath, actualDevice)
        except HardwareAccelerationError:
            raise
        except Exception as error:
            raise ProviderOperationError(f"Docling failed to parse {filePath.name}") from error
        return ParsedDocument(
            content=parsedContent,
            parserName="docling",
            parserVersion="2.x-pinned-at-install",
            acceleratorReports=(acceleratorReport,),
        )

    def _convertFile(self, filePath: Path, actualDevice: str) -> str:
        try:
            from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as error:
            raise ProviderOperationError(
                "Docling is not installed; install the ingestion dependency group"
            ) from error
        deviceMapping = {
            "mps": AcceleratorDevice.MPS,
            "cuda": AcceleratorDevice.CUDA,
            "cpu": AcceleratorDevice.CPU,
        }
        pipelineOptions = PdfPipelineOptions()
        pipelineOptions.enable_remote_services = False
        pipelineOptions.allow_external_plugins = False
        pipelineOptions.do_ocr = True
        pipelineOptions.do_table_structure = True
        pipelineOptions.accelerator_options = AcceleratorOptions(
            num_threads=8,
            device=deviceMapping.get(actualDevice, AcceleratorDevice.CPU),
        )
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipelineOptions)}
        )
        conversionResult = converter.convert(filePath)
        markdownContent = conversionResult.document.export_to_markdown()
        if not markdownContent.strip():
            raise ProviderOperationError("Docling produced an empty document")
        return markdownContent
