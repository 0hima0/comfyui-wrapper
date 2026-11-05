"""Optional, job-scoped ComfyUI WebSocket progress; HTTP owns completion."""
import json
import logging
import math
from urllib.parse import urlsplit, urlunsplit, urlencode

logger = logging.getLogger(__name__)


def open_socket(url, client_id):
    socket = None
    try:
        import websocket
        parsed = urlsplit(url)
        endpoint = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc,
                              parsed.path.rstrip('/')+'/ws', urlencode({'clientId':client_id}), ''))
        socket = websocket.create_connection(endpoint, timeout=1)
        socket.settimeout(.02)
        return socket
    except Exception:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        logger.info('ComfyUI step progress unavailable; continuing HTTP history polling.')
        return None


class ComfyProgress:
    def __init__(self, url, client_id, graph):
        self.socket = open_socket(url, client_id)
        self.graph = graph
        self.prompt_id = None
        self.active = False
        self.current_node = None

    def bind(self, prompt_id):
        self.prompt_id = prompt_id

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

    def event(self, message):
        if not isinstance(message, dict) or not isinstance(message.get('data'), dict):
            return None
        kind, data = message.get('type'), message['data']
        prompt_id = data.get('prompt_id')
        if prompt_id is not None and str(prompt_id) != self.prompt_id:
            return None
        if kind in ('execution_start', 'executing', 'execution_success'):
            if prompt_id is None:
                return None
            self.active = True
            self.current_node = str(data['node']) if data.get('node') is not None else None
            node_type = self.graph.get(self.current_node, {}).get('class_type', '')
            detail = {'KSampler':'画像を生成しています…', 'VAEDecode':'生成結果を画像に変換しています…',
                      'SaveImage':'ComfyUIで画像を保存しています…'}.get(node_type, 'モデル読み込み・Prompt処理を実行しています…')
            if kind == 'execution_success' or (kind == 'executing' and data.get('node') is None):
                self.active = False
                detail = '生成結果を確認しています…'
            return dict(stage='generate', detail=detail)
        if kind != 'progress' or not self.active:
            return None
        node = str(data.get('node', self.current_node))
        if node != self.current_node or self.graph.get(node, {}).get('class_type') != 'KSampler':
            return None
        value, maximum = data.get('value'), data.get('max')
        if (type(value) not in (int,float) or type(maximum) not in (int,float)
                or not math.isfinite(value) or not math.isfinite(maximum) or not 0 <= value <= maximum or maximum <= 0):
            return None
        return dict(stage='generate', detail=f'画像を生成しています…（{value:g} / {maximum:g}ステップ）',
                    current=value, total=maximum)

    def poll(self):
        if self.socket is None:
            return None
        latest = None
        # Drain buffered events without delaying the authoritative history poll.
        for _ in range(100):
            try:
                raw = self.socket.recv()
            except TimeoutError:
                break
            except Exception as error:
                # websocket-client uses its own timeout exception, not TimeoutError.
                if type(error).__name__ == 'WebSocketTimeoutException':
                    break
                self.close()
                return dict(stage='generate', detail='進捗の接続が切れました。ComfyUIの完了を確認しています…')
            if raw == '':
                self.close()
                return dict(stage='generate', detail='ステップ情報なしでComfyUIの完了を確認しています…')
            if not isinstance(raw, str):
                continue
            try:
                update = self.event(json.loads(raw))
            except (ValueError, TypeError, KeyError):
                continue
            if update is not None:
                latest = update
        return latest
