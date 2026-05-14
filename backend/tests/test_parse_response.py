"""Unit tests for XFYunClient._parse_response method."""
import json
import sys
import os

# Add backend to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.xfyun_client import XFYunClient


def make_client():
    return XFYunClient(
        app_id="test_app_id",
        api_key="test_api_key",
        api_secret="test_api_secret",
    )


def test_parse_normal_response():
    """正常响应：提取并拼接 ws[].cw[].w 文本"""
    client = make_client()
    resp = {
        "code": 0,
        "message": "success",
        "data": {
            "status": 2,
            "result": {
                "ws": [
                    {"bg": 0, "cw": [{"w": "你好", "sc": 0}]},
                    {"bg": 0, "cw": [{"w": "世界", "sc": 0}]},
                ]
            },
        },
    }
    text, is_final = client._parse_response(json.dumps(resp))
    assert text == "你好世界"
    assert is_final is True


def test_parse_intermediate_response():
    """中间结果：status != 2，is_final 为 False"""
    client = make_client()
    resp = {
        "code": 0,
        "message": "success",
        "data": {
            "status": 1,
            "result": {
                "ws": [
                    {"bg": 0, "cw": [{"w": "你", "sc": 0}]},
                    {"bg": 0, "cw": [{"w": "好", "sc": 0}]},
                ]
            },
        },
    }
    text, is_final = client._parse_response(json.dumps(resp))
    assert text == "你好"
    assert is_final is False


def test_parse_error_code():
    """非零 code：返回空字符串和 is_final=True"""
    client = make_client()
    resp = {"code": 10001, "message": "auth failed"}
    text, is_final = client._parse_response(json.dumps(resp))
    assert text == ""
    assert is_final is True


def test_parse_invalid_json():
    """无效 JSON：返回空字符串和 is_final=True"""
    client = make_client()
    text, is_final = client._parse_response("not valid json {{{")
    assert text == ""
    assert is_final is True


def test_parse_empty_result():
    """空 result：返回空字符串"""
    client = make_client()
    resp = {
        "code": 0,
        "message": "success",
        "data": {"status": 2, "result": {}},
    }
    text, is_final = client._parse_response(json.dumps(resp))
    assert text == ""
    assert is_final is True


def test_parse_multiple_cw_per_ws():
    """单个 ws 中有多个 cw 项"""
    client = make_client()
    resp = {
        "code": 0,
        "message": "success",
        "data": {
            "status": 0,
            "result": {
                "ws": [
                    {"bg": 0, "cw": [{"w": "A", "sc": 0}, {"w": "B", "sc": 0}]},
                ]
            },
        },
    }
    text, is_final = client._parse_response(json.dumps(resp))
    assert text == "AB"
    assert is_final is False
