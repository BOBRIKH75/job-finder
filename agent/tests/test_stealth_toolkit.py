"""Tests for stealth_toolkit in cloud agent."""
import pytest
from src.stealth_toolkit import (
    StealthResult, list_available_tools, stealth_fetch,
    fetch_curl_cffi, TOOL_CHAIN,
)


def test_stealth_result():
    r = StealthResult(success=True, tool="test", html="<html>ok</html>", status_code=200)
    assert r.success and r.tool == "test" and r.cookies == []


def test_list_tools():
    tools = list_available_tools()
    assert len(tools) == 7
    available = {t["name"] for t in tools if t["available"]}
    assert "curl_cffi" in available


def test_tool_chain_order():
    assert [n for n, _ in TOOL_CHAIN][0] == "seleniumbase_uc"


def test_curl_cffi_httpbin():
    r = fetch_curl_cffi("https://httpbin.org/get")
    assert r.success and r.status_code == 200 and "httpbin" in r.html


def test_stealth_fetch_curl_only():
    r = stealth_fetch("https://httpbin.org/get", tools=["curl_cffi"])
    assert r.success and r.tool == "curl_cffi"


def test_bad_url_fails():
    r = fetch_curl_cffi("https://thisdomaindoesnotexist12345.com")
    assert not r.success
