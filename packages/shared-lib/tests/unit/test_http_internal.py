"""Unit tests for accounting_shared.http_internal module."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from accounting_shared.http_internal import post_json


class TestPostJson:
    """Tests for post_json function."""

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_success(self, mock_urlopen):
        """post_json should return status code and parsed JSON on success."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({"result": "ok"}).encode("utf-8")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        status, data = await post_json(
            "http://test.com/api",
            headers={"Authorization": "Bearer token"},
            body={"key": "value"},
        )

        assert status == 200
        assert data == {"result": "ok"}

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_with_http_error(self, mock_urlopen):
        """post_json should handle HTTP errors and return status code."""
        import urllib.error

        # Mock HTTP error
        mock_error = urllib.error.HTTPError(
            url="http://test.com/api",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(json.dumps({"error": "not found"}).encode("utf-8")),
        )
        mock_urlopen.side_effect = mock_error

        status, data = await post_json(
            "http://test.com/api",
            headers={},
            body={},
        )

        assert status == 404
        assert data == {"error": "not found"}

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_with_non_json_response(self, mock_urlopen):
        """post_json should handle non-JSON response gracefully."""
        # Mock response with non-JSON content
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"Not JSON content"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        status, data = await post_json(
            "http://test.com/api",
            headers={},
            body={},
        )

        assert status == 200
        assert data == "Not JSON content"

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_sends_correct_request(self, mock_urlopen):
        """post_json should send correct request with headers and body."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        await post_json(
            "http://test.com/api",
            headers={"Authorization": "Bearer token", "Custom-Header": "value"},
            body={"key": "value", "nested": {"a": 1}},
            timeout=30.0,
        )

        # Verify the request was made
        mock_urlopen.assert_called_once()

        # Get the request object
        call_args = mock_urlopen.call_args
        request = call_args[0][0]

        # Verify request properties
        assert request.full_url == "http://test.com/api"
        assert request.method == "POST"
        # Headers are case-insensitive in HTTP
        assert request.get_header("Content-type") == "application/json"
        assert request.get_header("Authorization") == "Bearer token"
        assert request.get_header("Custom-header") == "value"

        # Verify request body
        body = json.loads(request.data.decode("utf-8"))
        assert body == {"key": "value", "nested": {"a": 1}}

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_default_timeout(self, mock_urlopen):
        """post_json should use default timeout of 10.0 seconds."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        await post_json(
            "http://test.com/api",
            headers={},
            body={},
        )

        # Verify timeout was set
        call_args = mock_urlopen.call_args
        assert call_args.kwargs.get("timeout") == 10.0

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_custom_timeout(self, mock_urlopen):
        """post_json should use custom timeout when provided."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        await post_json(
            "http://test.com/api",
            headers={},
            body={},
            timeout=30.0,
        )

        # Verify timeout was set
        call_args = mock_urlopen.call_args
        assert call_args.kwargs.get("timeout") == 30.0

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_with_empty_body(self, mock_urlopen):
        """post_json should handle empty body."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        status, data = await post_json(
            "http://test.com/api",
            headers={},
            body={},
        )

        assert status == 200
        assert data == {}

    @pytest.mark.asyncio
    @patch("accounting_shared.http_internal.urllib.request.urlopen")
    async def test_post_json_with_complex_body(self, mock_urlopen):
        """post_json should handle complex nested body."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"{}"
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        complex_body = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "nested": {"key": "value"},
        }

        status, data = await post_json(
            "http://test.com/api",
            headers={},
            body=complex_body,
        )

        assert status == 200

        # Verify the request body was correctly serialized
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))
        assert body == complex_body
