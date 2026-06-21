"""Offline parser registry with local normalization and explicit accelerator diagnostics."""

from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from cortex.config import Settings
from cortex.domain.chunking import normalizeContent
from cortex.errors import HardwareAccelerationError, InputValidationError, ProviderOperationError
from cortex.services.accelerator import (
    AcceleratorReport,
    detectAvailableAccelerator,
    enforceAcceleratorBinding,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"
HTML_MIME_TYPES = {"text/html"}
TEXT_MIME_TYPES = {"text/plain", "text/markdown"}
CSV_MIME_TYPES = {"text/csv"}


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Return normalized parser output and device diagnostics without hiding failures."""

    content: str
    parserName: str
    parserVersion: str
    extractionDiagnostics: dict[str, object]
    acceleratorReports: tuple[AcceleratorReport, ...]


class DocumentParser(Protocol):
    """Define the replaceable parser contract used by ingestion workers."""

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Parse one validated local file into normalized structured text."""
        ...


class PlainTextParser:
    """Parse UTF-8 text and markdown fixtures without invoking OCR or remote providers."""

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
        normalizedContent = normalizeContent(content)
        return ParsedDocument(
            content=normalizedContent,
            parserName="plain-text",
            parserVersion="1.1.0",
            extractionDiagnostics={"lineCount": len(normalizedContent.splitlines())},
            acceleratorReports=(),
        )


class CsvTextParser:
    """Convert local CSV files into a stable row-oriented textual representation."""

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Read CSV rows deterministically so retrieval can cite table content consistently."""
        if not await asyncio.to_thread(filePath.is_file):
            raise InputValidationError(f"file does not exist: {filePath}")
        try:
            rawContent = await asyncio.to_thread(filePath.read_text, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProviderOperationError(f"failed to read CSV document: {filePath.name}") from error
        reader = csv.reader(rawContent.splitlines())
        rows = list(reader)
        if not rows:
            raise InputValidationError("parsed CSV cannot be empty")
        header = rows[0]
        bodyRows = rows[1:]
        normalizedRows = [
            " | ".join(f"{column}: {value}" for column, value in zip(header, row, strict=False))
            for row in bodyRows
        ]
        content = normalizeContent(
            "\n".join(
                [
                    f"CSV file: {filePath.name}",
                    f"Columns: {', '.join(header)}",
                    *normalizedRows,
                ]
            )
        )
        return ParsedDocument(
            content=content,
            parserName="csv-text",
            parserVersion="1.0.0",
            extractionDiagnostics={"rowCount": len(bodyRows), "columnCount": len(header)},
            acceleratorReports=(),
        )


class HtmlTextParser:
    """Flatten HTML into stable plain text without enabling remote rendering or scripts."""

    async def parseFile(self, filePath: Path) -> ParsedDocument:
        """Strip local HTML to retrieval-friendly text with minimal structure retained."""
        if not await asyncio.to_thread(filePath.is_file):
            raise InputValidationError(f"file does not exist: {filePath}")
        try:
            markup = await asyncio.to_thread(filePath.read_text, encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ProviderOperationError(
                f"failed to read HTML document: {filePath.name}"
            ) from error
        parser = _TextExtractingHtmlParser()
        parser.feed(markup)
        extractedText = normalizeContent(parser.toText())
        return ParsedDocument(
            content=extractedText,
            parserName="html-text",
            parserVersion="1.0.0",
            extractionDiagnostics={"characterCount": len(extractedText)},
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
        normalizedContent = normalizeContent(parsedContent)
        return ParsedDocument(
            content=normalizedContent,
            parserName="docling",
            parserVersion="2.x-pinned-at-install",
            extractionDiagnostics={"characterCount": len(normalizedContent)},
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


class ParserRegistry:
    """Resolve the correct local parser for an allowlisted MIME type."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._plainTextParser = PlainTextParser()
        self._csvParser = CsvTextParser()
        self._htmlParser = HtmlTextParser()
        self._doclingParser = DoclingParser(settings)

    def getParser(self, mimeType: str) -> DocumentParser:
        """Return a deterministic parser implementation for one accepted MIME type."""
        normalizedMimeType = mimeType.strip().lower()
        if normalizedMimeType in TEXT_MIME_TYPES:
            return self._plainTextParser
        if normalizedMimeType in CSV_MIME_TYPES:
            return self._csvParser
        if normalizedMimeType in HTML_MIME_TYPES:
            return self._htmlParser
        if normalizedMimeType in {PDF_MIME, DOCX_MIME}:
            return self._doclingParser
        raise InputValidationError(f"unsupported MIME type: {mimeType}")

    async def parseBytes(
        self,
        content: bytes,
        mimeType: str,
        fileName: str,
    ) -> ParsedDocument:
        """Write source bytes to a temporary file so parser adapters stay path-based."""
        if not content:
            raise InputValidationError("source content cannot be empty")
        suffix = Path(fileName).suffix or _guessSuffix(mimeType)
        try:
            with NamedTemporaryFile(delete=False, suffix=suffix) as temporaryFile:
                temporaryFile.write(content)
                temporaryPath = Path(temporaryFile.name)
        except OSError as error:
            raise ProviderOperationError("failed to stage temporary source file") from error
        try:
            parser = self.getParser(mimeType)
            return await parser.parseFile(temporaryPath)
        finally:
            try:
                await asyncio.to_thread(temporaryPath.unlink)
            except OSError:
                pass


class _TextExtractingHtmlParser(HTMLParser):
    """Collect visible HTML text while dropping script and style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._ignoredDepth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignoredDepth += 1
        if tag in {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignoredDepth > 0:
            self._ignoredDepth -= 1
        if tag in {"p", "div", "section", "article", "li", "tr", "br"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignoredDepth == 0 and data.strip():
            self._chunks.append(data)

    def toText(self) -> str:
        """Return all visible text collected from the parsed document."""
        content = "".join(self._chunks)
        if not content.strip():
            raise InputValidationError("parsed HTML cannot be empty")
        return content


def _guessSuffix(mimeType: str) -> str:
    """Map supported MIME types to deterministic temporary file suffixes."""
    if mimeType == PDF_MIME:
        return ".pdf"
    if mimeType == DOCX_MIME:
        return ".docx"
    if mimeType in CSV_MIME_TYPES:
        return ".csv"
    if mimeType in HTML_MIME_TYPES:
        return ".html"
    if mimeType == "text/markdown":
        return ".md"
    return ".txt"
