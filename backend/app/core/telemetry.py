"""OpenTelemetry SDK setup — traces, metrics, and logs for all backend services.

Supports multiple simultaneous export targets (console, file, OTLP, Logfire, custom)
configured via :class:`~app.core.config.TelemetrySettings`.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

if TYPE_CHECKING:
    from app.core.config import TelemetrySettings

logger: Logger = logging.getLogger(__name__)

_telemetry_initialised = False


class ExporterFactory:
    def __init__(self, config):
        self._config = config

    def build_trace_processors(self):
        processors = []
        for exporter_type in self._config.exporters:
            exporter = self._build_span_exporter(exporter_type)
            if exporter is not None:
                processors.append(BatchSpanProcessor(exporter))
        return processors

    def _build_span_exporter(self, exporter_type):
        from app.core.config import TelemetryExporterType
        if exporter_type == TelemetryExporterType.console:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            return ConsoleSpanExporter()
        if exporter_type == TelemetryExporterType.file:
            return _FileSpanExporter(self._config.file)
        if exporter_type == TelemetryExporterType.otlp:
            return self._build_otlp_span_exporter()
        if exporter_type == TelemetryExporterType.logfire:
            return self._build_logfire_span_exporter()
        if exporter_type == TelemetryExporterType.custom:
            return self._build_custom_span_exporter()
        logger.warning("Unknown exporter type '%s' — skipping", exporter_type)
        return None

    def _build_otlp_span_exporter(self):
        opts = self._config.otlp
        if opts.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            return OTLPSpanExporter(endpoint=opts.endpoint, insecure=opts.insecure)
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPSpanExporterHTTP
        return OTLPSpanExporterHTTP(endpoint=f"{opts.endpoint}/v1/traces")

    def _build_logfire_span_exporter(self):
        token = self._config.logfire.token
        if not token:
            logger.warning("Logfire exporter requested but no token configured — skipping")
            return None
        try:
            import logfire
            logfire.configure(token=token, send_to_logfire=True)
            logger.info("Logfire initialised")
            return None
        except ImportError:
            logger.warning("logfire package not installed — skipping Logfire exporter")
            return None

    def _build_custom_span_exporter(self):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPSpanExporterHTTP
        endpoint = self._config.custom.endpoint
        return OTLPSpanExporterHTTP(endpoint=f"{endpoint.rstrip('/')}/v1/traces")

    def build_metric_readers(self):
        readers = []
        for exporter_type in self._config.exporters:
            exporter = self._build_metric_exporter(exporter_type)
            if exporter is not None:
                readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=30_000))
        return readers

    def _build_metric_exporter(self, exporter_type):
        from app.core.config import TelemetryExporterType
        if exporter_type == TelemetryExporterType.console:
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
            return ConsoleMetricExporter()
        if exporter_type == TelemetryExporterType.file:
            return _FileMetricExporter(self._config.file)
        if exporter_type == TelemetryExporterType.otlp:
            return self._build_otlp_metric_exporter()
        if exporter_type == TelemetryExporterType.logfire:
            return None
        if exporter_type == TelemetryExporterType.custom:
            return self._build_custom_metric_exporter()
        return None

    def _build_otlp_metric_exporter(self):
        opts = self._config.otlp
        if opts.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            return OTLPMetricExporter(endpoint=opts.endpoint, insecure=opts.insecure)
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPMetricExporterHTTP
        return OTLPMetricExporterHTTP(endpoint=f"{opts.endpoint}/v1/metrics")

    def _build_custom_metric_exporter(self):
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPMetricExporterHTTP
        endpoint = self._config.custom.endpoint
        return OTLPMetricExporterHTTP(endpoint=f"{endpoint.rstrip('/')}/v1/metrics")

    def build_log_processors(self):
        processors = []
        for exporter_type in self._config.exporters:
            exporter = self._build_log_exporter(exporter_type)
            if exporter is not None:
                processors.append(BatchLogRecordProcessor(exporter))
        return processors

    def _build_log_exporter(self, exporter_type):
        from app.core.config import TelemetryExporterType
        if exporter_type == TelemetryExporterType.console:
            from opentelemetry.sdk._logs.export import ConsoleLogExporter
            return ConsoleLogExporter()
        if exporter_type == TelemetryExporterType.file:
            return _FileLogExporter(self._config.file)
        if exporter_type == TelemetryExporterType.otlp:
            return self._build_otlp_log_exporter()
        if exporter_type == TelemetryExporterType.logfire:
            return None
        if exporter_type == TelemetryExporterType.custom:
            return self._build_custom_log_exporter()
        return None

    def _build_otlp_log_exporter(self):
        opts = self._config.otlp
        if opts.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
            return OTLPLogExporter(endpoint=opts.endpoint, insecure=opts.insecure)
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP
        return OTLPLogExporterHTTP(endpoint=f"{opts.endpoint}/v1/logs")

    def _build_custom_log_exporter(self):
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as OTLPLogExporterHTTP
        endpoint = self._config.custom.endpoint
        return OTLPLogExporterHTTP(endpoint=f"{endpoint.rstrip('/')}/v1/logs")


def _ensure_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


class _FileSpanExporter:
    def __init__(self, opts) -> None:
        _ensure_dir(opts.path)
        self._handler = logging.handlers.RotatingFileHandler(
            opts.path, maxBytes=opts.max_bytes, backupCount=opts.backup_count
        )
        self._span_logger = logging.getLogger("otel.spans")
        self._span_logger.addHandler(self._handler)
        self._span_logger.setLevel(logging.DEBUG)
        self._span_logger.propagate = False

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult
        try:
            for span in spans:
                self._span_logger.info(str(span))
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._handler.close()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        self._handler.flush()
        return True


class _FileMetricExporter:
    def __init__(self, opts) -> None:
        _ensure_dir(opts.path)
        self._handler = logging.handlers.RotatingFileHandler(
            opts.path, maxBytes=opts.max_bytes, backupCount=opts.backup_count
        )
        self._metric_logger = logging.getLogger("otel.metrics")
        self._metric_logger.addHandler(self._handler)
        self._metric_logger.setLevel(logging.DEBUG)
        self._metric_logger.propagate = False

    @property
    def _preferred_temporality(self):
        from opentelemetry.sdk.metrics.export import AggregationTemporality
        # Return a dict mapping instrument classes to temporality
        # Using empty dict means default (CUMULATIVE) for all instruments
        return {}

    @property
    def _preferred_aggregation(self):
        # Return a dict mapping instrument classes to aggregation
        # Using empty dict means default aggregation for all instruments
        return {}

    def export(self, metrics_data, timeout_millis: int = 10_000):
        from opentelemetry.sdk.metrics.export import MetricExportResult
        try:
            self._metric_logger.info(str(metrics_data))
            return MetricExportResult.SUCCESS
        except Exception:
            return MetricExportResult.FAILURE

    def shutdown(self, timeout_millis: int = 30_000, **kwargs) -> None:
        """Shutdown the exporter. Accepts timeout_millis or timeout as kwargs."""
        self._handler.close()

    def force_flush(self, timeout_millis: int = 10_000) -> bool:
        self._handler.flush()
        return True


class _FileLogExporter:
    def __init__(self, opts) -> None:
        _ensure_dir(opts.path)
        self._handler = logging.handlers.RotatingFileHandler(
            opts.path, maxBytes=opts.max_bytes, backupCount=opts.backup_count
        )
        # Set a simple formatter that just writes the message (we'll format it ourselves)
        formatter = logging.Formatter('%(message)s')
        self._handler.setFormatter(formatter)
        
        self._log_logger = logging.getLogger("otel.logs")
        self._log_logger.addHandler(self._handler)
        self._log_logger.setLevel(logging.DEBUG)
        self._log_logger.propagate = False

    def export(self, batch):
        from opentelemetry.sdk._logs.export import LogExportResult
        from datetime import datetime
        try:
            for readable_log in batch:
                log_record = readable_log.log_record
                
                # Format timestamp
                timestamp = datetime.fromtimestamp(log_record.timestamp / 1e9).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                # Get severity/level
                severity = log_record.severity_text or 'INFO'
                
                # Get logger name from instrumentation scope
                logger_name = readable_log.instrumentation_scope.name if readable_log.instrumentation_scope else 'root'
                
                # Get the actual log message
                body = log_record.body if log_record.body else ''
                
                # Format attributes if present
                attrs = ''
                if log_record.attributes:
                    attrs = ' | ' + ' '.join(f'{k}={v}' for k, v in log_record.attributes.items())
                
                # Format as standard log line
                log_line = f"{timestamp} - {logger_name} - {severity} - {body}{attrs}"
                self._log_logger.info(log_line)
                
            return LogExportResult.SUCCESS
        except Exception as e:
            import traceback
            self._log_logger.error(f"Failed to export logs: {e}\n{traceback.format_exc()}")
            return LogExportResult.FAILURE

    def shutdown(self) -> None:
        self._handler.close()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        self._handler.flush()
        return True


def setup_telemetry(config: "TelemetrySettings") -> None:
    """Configure TracerProvider, MeterProvider, and LoggerProvider from *config*.

    Delegates all exporter construction to ExporterFactory.
    Registers no-op providers for disabled signals.
    Must be called once on application startup before any request is served.
    """
    global _telemetry_initialised
    if _telemetry_initialised:
        return

    all_disabled = (
        not config.traces_enabled
        and not config.metrics_enabled
        and not config.logs_enabled
    )
    if all_disabled:
        logger.info("OpenTelemetry is fully disabled — skipping setup")
        _telemetry_initialised = True
        return

    resource = Resource.create({SERVICE_NAME: config.service_name})
    factory = ExporterFactory(config)

    # Tracer Provider
    if config.traces_enabled:
        processors = factory.build_trace_processors()
        tracer_provider = TracerProvider(resource=resource)
        for processor in processors:
            tracer_provider.add_span_processor(processor)
        trace.set_tracer_provider(tracer_provider)
    else:
        # Use SDK TracerProvider (no processors) as the no-op provider.
        # ProxyTracerProvider must NOT be used here: its get_tracer() calls the
        # module-level _TRACER_PROVIDER.get_tracer(), which points back to itself
        # when it is the global provider, causing infinite recursion.
        trace.set_tracer_provider(TracerProvider(resource=resource))
        logger.info("Traces disabled — no-op TracerProvider registered")

    # Meter Provider
    if config.metrics_enabled:
        readers = factory.build_metric_readers()
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        metrics.set_meter_provider(meter_provider)
    else:
        metrics.set_meter_provider(MeterProvider(resource=resource))
        logger.info("Metrics disabled — no-op MeterProvider registered")

    # Logger Provider
    if config.logs_enabled:
        log_processors = factory.build_log_processors()
        logger_provider = LoggerProvider(resource=resource)
        for proc in log_processors:
            logger_provider.add_log_record_processor(proc)
        otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        logging.getLogger().addHandler(otel_handler)
    else:
        logger.info("Logs disabled — skipping LoggerProvider registration")

    # W3C TraceContext propagation
    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))

    # Auto-instrumentation
    _instrument_libraries()

    # Per-component log levels
    _apply_log_levels(config.log_levels)

    _telemetry_initialised = True
    logger.info(
        "OpenTelemetry initialised — service=%s exporters=%s",
        config.service_name,
        [e.value for e in config.exporters],
    )


def _apply_log_levels(log_levels: dict) -> None:
    for component, level_str in log_levels.items():
        level = getattr(logging, level_str.upper(), None)
        if level is None:
            logger.warning("Unknown log level '%s' for component '%s'", level_str, component)
            continue
        if component == "root":
            logging.getLogger().setLevel(level)
        else:
            logging.getLogger(component).setLevel(level)


def _instrument_libraries() -> None:
    """Apply auto-instrumentation patches for FastAPI, SQLAlchemy, Redis, and httpx."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument()
        logger.debug("FastAPI instrumented")
    except Exception as exc:  # pragma: no cover
        logger.warning("FastAPI instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
        logger.debug("SQLAlchemy instrumented")
    except Exception as exc:  # pragma: no cover
        logger.warning("SQLAlchemy instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
        logger.debug("Redis instrumented")
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis instrumentation failed: %s", exc)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.debug("httpx instrumented")
    except Exception as exc:  # pragma: no cover
        logger.warning("httpx instrumentation failed: %s", exc)
