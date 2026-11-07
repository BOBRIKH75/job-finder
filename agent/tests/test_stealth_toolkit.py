"""Tests for stealth_toolkit in cloud agent."""
import socket
import pytest
from src.stealth_toolkit import (
    StealthResult, list_available_tools, stealth_fetch,
    fetch_curl_cffi, TOOL_CHAIN,
)


def _online():
    try:
        socket.create_connection(("httpbin.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


def _has_curl_cffi():
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False


needs_network = pytest.mark.skipif(
    not (_has_curl_cffi() and _online()),
    reason="needs curl_cffi + internet access (httpbin.org)",
)


def test_stealth_result():
    r = StealthResult(success=True, tool="test", html="<html>ok</html>", status_code=200)
    assert r.success and r.tool == "test" and r.cookies == []


def test_list_tools():
    tools = list_available_tools()
    assert len(tools) == len(TOOL_CHAIN) == 8
    assert {t["name"] for t in tools} == {n for n, _ in TOOL_CHAIN}


def test_tool_chain_order():
    assert [n for n, _ in TOOL_CHAIN][0] == "curl_cffi"  # cheapest tool first


@needs_network
def test_curl_cffi_httpbin():
    r = fetch_curl_cffi("https://httpbin.org/get")
    assert r.success and r.status_code == 200 and "httpbin" in r.html


@needs_network
def test_stealth_fetch_curl_only():
    r = stealth_fetch("https://httpbin.org/get", tools=["curl_cffi"])
    assert r.success and r.tool == "curl_cffi"


def test_bad_url_fails():
    r = fetch_curl_cffi("https://thisdomaindoesnotexist12345.com")
    assert not r.success
