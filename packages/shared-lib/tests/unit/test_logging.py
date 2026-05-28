"""Unit tests for accounting_shared.logging module."""

from __future__ import annotations

import logging
from unittest.mock import patch

import structlog

from accounting_shared.logging import setup_logging


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_does_not_raise(self):
        """setup_logging should not raise any exceptions."""
        setup_logging("DEBUG")
        setup_logging("INFO")
        setup_logging("WARNING")
        setup_logging("ERROR")
        setup_logging("CRITICAL")

    def test_setup_logging_configures_root_logger(self):
        """setup_logging should configure root logger with correct level."""
        setup_logging("INFO")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_setup_logging_sets_log_level(self):
        """setup_logging should set the specified log level."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            setup_logging(level)
            root_logger = logging.getLogger()
            assert root_logger.level == getattr(logging, level)

    def test_setup_logging_handles_lowercase_level(self):
        """setup_logging should handle lowercase log level."""
        setup_logging("info")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_setup_logging_clears_existing_handlers(self):
        """setup_logging should clear existing handlers."""
        root_logger = logging.getLogger()
        # Add a dummy handler
        dummy_handler = logging.StreamHandler()
        root_logger.addHandler(dummy_handler)

        setup_logging("DEBUG")

        # Should have exactly one handler after setup
        assert len(root_logger.handlers) == 1
        assert root_logger.handlers[0] is not dummy_handler

    def test_setup_logging_adds_handler_to_root_logger(self):
        """setup_logging should add a StreamHandler to root logger."""
        setup_logging("DEBUG")
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    def test_setup_logging_handler_formatter(self):
        """setup_logging handler should have ProcessorFormatter."""
        setup_logging("DEBUG")
        root_logger = logging.getLogger()
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)

    def test_setup_logging_calls_structlog_configure(self):
        """setup_logging should call structlog.configure."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("DEBUG")
            mock_configure.assert_called_once()

    def test_setup_logging_uses_correct_processors_for_debug(self):
        """setup_logging should use appropriate processors for DEBUG level."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("DEBUG")

            call_args = mock_configure.call_args
            processors = call_args.kwargs.get("processors", call_args[1].get("processors", []))

            # Should have processors
            assert len(processors) > 0

            # Last processor should be wrap_for_formatter
            last_processor = processors[-1]
            assert last_processor == structlog.stdlib.ProcessorFormatter.wrap_for_formatter

    def test_setup_logging_uses_correct_processors_for_info(self):
        """setup_logging should use appropriate processors for INFO level."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("INFO")

            call_args = mock_configure.call_args
            processors = call_args.kwargs.get("processors", call_args[1].get("processors", []))

            # Should have processors
            assert len(processors) > 0

            # Last processor should be wrap_for_formatter
            last_processor = processors[-1]
            assert last_processor == structlog.stdlib.ProcessorFormatter.wrap_for_formatter

    def test_setup_logging_configures_logger_factory(self):
        """setup_logging should configure logger factory."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("DEBUG")

            call_args = mock_configure.call_args
            logger_factory = call_args.kwargs.get(
                "logger_factory", call_args[1].get("logger_factory")
            )
            assert isinstance(logger_factory, structlog.stdlib.LoggerFactory)

    def test_setup_logging_configures_context_class(self):
        """setup_logging should configure context class as dict."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("DEBUG")

            call_args = mock_configure.call_args
            context_class = call_args.kwargs.get("context_class", call_args[1].get("context_class"))
            assert context_class is dict

    def test_setup_logging_enables_cache_logger(self):
        """setup_logging should enable cache_logger_on_first_use."""
        with patch("structlog.configure") as mock_configure:
            setup_logging("DEBUG")

            call_args = mock_configure.call_args
            cache = call_args.kwargs.get(
                "cache_logger_on_first_use",
                call_args[1].get("cache_logger_on_first_use"),
            )
            assert cache is True
