# -*- coding: utf-8 -*-
"""
腾讯云 SCF Python 版本反向代理
无需 Node.js，纯 Python 实现
"""
import json
import os
import urllib.request
import urllib.error
from urllib.parse import urlencode, urlparse


def main_handler(event, context):
    """
    腾讯云 SCF 主处理函数

    Args:
        event: API 网关事件对象
        context: 函数上下文

    Returns:
        dict: API 网关响应格式
    """

    # 获取目标后端 URL
    target_base_url = os.environ.get('TARGET_BASE_URL')
    if not target_base_url:
        return error_response(500, 'TARGET_BASE_URL environment variable is required')

    try:
        # 解析请求信息
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '/')
        query_string = event.get('queryString', {})
        headers = event.get('headers', {})
        body = event.get('body', '')
        is_base64 = event.get('isBase64Encoded', False)

        # 构建完整的目标 URL
        if query_string:
            query_params = urlencode(query_string)
            target_url = f"{target_base_url}{path}?{query_params}"
        else:
            target_url = f"{target_base_url}{path}"

        # CORS 预检请求处理
        if http_method == 'OPTIONS':
            return {
                'isBase64Encoded': False,
                'statusCode': 204,
                'headers': get_cors_headers(),
                'body': ''
            }

        # 准备转发请求头
        forward_headers = {}
        for key, value in headers.items():
            key_lower = key.lower()
            # 跳过 Cloudflare 特有头和 Host 头
            if key_lower in ['host', 'cf-connecting-ip', 'cf-ray',
                            'cf-visitor', 'x-forwarded-for', 'x-forwarded-proto']:
                continue
            forward_headers[key] = value

        # 设置正确的 Host 头
        parsed_url = urlparse(target_base_url)
        forward_headers['Host'] = parsed_url.netloc

        # 解码 Base64 请求体（如果有）
        if body and is_base64:
            import base64
            body = base64.b64decode(body).decode('utf-8')

        # 创建请求对象
        req = urllib.request.Request(
            target_url,
            data=body.encode('utf-8') if body else None,
            headers=forward_headers,
            method=http_method
        )

        # 发送请求并获取响应
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read()
                response_headers = dict(response.headers)

                # 添加 CORS 头
                response_headers.update(get_cors_headers())

                # 返回 Base64 编码的响应（兼容二进制数据）
                import base64
                return {
                    'isBase64Encoded': True,
                    'statusCode': response.status,
                    'headers': response_headers,
                    'body': base64.b64encode(response_body).decode('utf-8')
                }

        except urllib.error.HTTPError as e:
            # HTTP 错误（如 404, 500 等）
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            return {
                'isBase64Encoded': False,
                'statusCode': e.code,
                'headers': {**get_cors_headers(), 'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': f'Backend returned {e.code}',
                    'message': error_body[:500]  # 限制错误信息长度
                })
            }

    except Exception as e:
        # 其他异常（网络错误、超时等）
        print(f"Proxy error: {str(e)}")
        return error_response(502, f'Proxy error: {str(e)}')


def get_cors_headers():
    """返回 CORS 响应头"""
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
        'Access-Control-Max-Age': '86400'
    }


def error_response(status_code, message):
    """返回错误响应"""
    return {
        'isBase64Encoded': False,
        'statusCode': status_code,
        'headers': {**get_cors_headers(), 'Content-Type': 'application/json'},
        'body': json.dumps({'error': message})
    }
