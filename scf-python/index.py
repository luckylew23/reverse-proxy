# -*- coding: utf-8 -*-
"""
腾讯云 SCF Python 版本反向代理
无需 Node.js，纯 Python 实现
"""
import json
import os
import base64
import urllib.request
import urllib.error
from urllib.parse import urlencode, urlparse


def main_handler(event, context):
    """腾讯云 SCF 主处理函数"""

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

        # 调试日志
        print(f"[DEBUG] httpMethod={http_method}")
        print(f"[DEBUG] path={path}")
        print(f"[DEBUG] queryString={query_string}")
        print(f"[DEBUG] headers={headers}")
        print(f"[DEBUG] target_base_url={target_base_url}")

        # 构建完整的目标 URL
        if query_string:
            query_params = urlencode(query_string)
            target_url = f"{target_base_url}{path}?{query_params}"
        else:
            target_url = f"{target_base_url}{path}"

        print(f"[DEBUG] target_url={target_url}")

        # CORS 预检请求处理
        if http_method == 'OPTIONS':
            return {
                'isBase64Encoded': False,
                'statusCode': 204,
                'headers': get_cors_headers(),
                'body': ''
            }

        # 准备转发请求头（统一小写 key）
        forward_headers = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in ['host', 'cf-connecting-ip', 'cf-ray',
                            'cf-visitor', 'x-forwarded-for', 'x-forwarded-proto',
                            'accept-encoding', 'content-length']:
                continue
            forward_headers[key_lower] = value

        # 设置正确的 Host 头
        parsed_url = urlparse(target_base_url)
        forward_headers['host'] = parsed_url.netloc

        # 不接受压缩，确保拿到原始文本
        forward_headers['accept-encoding'] = 'identity'

        # 解码 Base64 请求体（如果有）
        if body and is_base64:
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
                print(f"[DEBUG] response status={response.status}")
                print(f"[DEBUG] response_body length={len(response_body)}")

                # 统一构建响应头（全部用小写 key）
                response_headers = {}
                for key, value in response.headers.items():
                    key_lower = key.lower()
                    # 移除 hop-by-hop 和引起问题的头
                    if key_lower in ['transfer-encoding', 'connection', 'content-encoding',
                                     'content-length', 'keep-alive',
                                     'content-disposition']:
                        continue
                    response_headers[key_lower] = value

                # 打印实际 Content-Type
                print(f"[DEBUG] response content-type={response_headers.get('content-type', 'MISSING')}")

                # 添加 CORS 头
                response_headers.update(get_cors_headers())

                # 确保 content-type 存在（防止 SCF 平台自动加 content-disposition）
                if 'content-type' not in response_headers and 'Content-Type' not in response_headers:
                    response_headers['content-type'] = 'text/plain; charset=utf-8'

                # 强制移除 content-disposition（SCF 平台可能自动添加，导致浏览器下载）
                response_headers.pop('content-disposition', None)
                response_headers.pop('Content-Disposition', None)

                # 判断是否为文本
                content_type = response_headers.get('content-type', '')
                is_text = any(t in content_type for t in [
                    'text/', 'application/json', 'application/javascript',
                    'application/xml', 'application/xhtml'
                ])

                # 如果没有 Content-Type，尝试根据内容判断
                if not content_type:
                    try:
                        response_body.decode('utf-8')
                        is_text = True
                        response_headers['content-type'] = 'application/json'
                        print(f"[DEBUG] no content-type, detected as text")
                    except (UnicodeDecodeError, Exception):
                        is_text = False
                        response_headers['content-type'] = 'application/octet-stream'
                        print(f"[DEBUG] no content-type, detected as binary")

                print(f"[DEBUG] is_text={is_text}")

                if is_text:
                    # 文本响应：直接返回，不 Base64
                    body_str = response_body.decode('utf-8', errors='replace')

                    # 对 JSON 响应，改为 text/plain 让浏览器直接显示而非下载
                    # HTML 响应保持 text/html 不变
                    if 'application/json' in content_type:
                        response_headers['content-type'] = 'text/plain; charset=utf-8'
                    elif 'text/html' in content_type:
                        response_headers['content-type'] = 'text/html; charset=utf-8'

                    # 强制移除 content-disposition（防止浏览器下载）
                    response_headers.pop('content-disposition', None)
                    response_headers.pop('Content-Disposition', None)

                    print(f"[DEBUG] returning as text, length={len(body_str)}, content-type={response_headers.get('content-type')}")
                    return {
                        'isBase64Encoded': False,
                        'statusCode': response.status,
                        'headers': response_headers,
                        'body': body_str
                    }
                else:
                    # 二进制响应：Base64 编码
                    body_b64 = base64.b64encode(response_body).decode('utf-8')
                    print(f"[DEBUG] returning as base64, length={len(body_b64)}")
                    return {
                        'isBase64Encoded': True,
                        'statusCode': response.status,
                        'headers': response_headers,
                        'body': body_b64
                    }

        except urllib.error.HTTPError as e:
            # HTTP 错误（如 404, 500 等）
            error_body = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
            print(f"[DEBUG] HTTPError: code={e.code}, body={error_body[:200]}")
            return {
                'isBase64Encoded': False,
                'statusCode': e.code,
                'headers': {**get_cors_headers(), 'content-type': 'application/json'},
                'body': json.dumps({
                    'error': f'Backend returned {e.code}',
                    'message': error_body[:500]
                })
            }

    except Exception as e:
        print(f"Proxy error: {str(e)}")
        return error_response(502, f'Proxy error: {str(e)}')


def get_cors_headers():
    """返回 CORS 响应头（全部小写 key）"""
    return {
        'access-control-allow-origin': '*',
        'access-control-allow-methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'access-control-allow-headers': 'Content-Type, Authorization, X-Requested-With',
        'access-control-max-age': '86400'
    }


def error_response(status_code, message):
    """返回错误响应"""
    return {
        'isBase64Encoded': False,
        'statusCode': status_code,
        'headers': {**get_cors_headers(), 'content-type': 'application/json'},
        'body': json.dumps({'error': message})
    }
