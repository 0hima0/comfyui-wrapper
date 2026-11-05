"""Explicit settings review and save, guarded like other UI changes."""
from flask import jsonify, request
from comfyui_wrapper.infrastructure.http_support import require_ui_request
from comfyui_wrapper.settings.config_editor import ConfigConflict, validate
from comfyui_wrapper.integrations import comfy_client


def register(app,services):
    @app.route('/api/app-settings',methods=['GET','POST','PUT'])
    def application_settings():
        require_ui_request()
        editor=app.extensions.get('config_editor')
        if editor is None:return jsonify(error='設定ファイルを指定してWebUIを起動してください。'),503
        try:
            if request.method=='GET':return jsonify(editor.read())
            data=request.get_json(silent=True)
            if not isinstance(data,dict):raise ValueError('設定データが不正です。')
            if request.method=='POST' and data.get('action')=='connection':
                checked=validate(data.get('settings'),editor.path)
                results=[]
                targets=[('ComfyUI',checked['comfy_url'],'/system_stats')]+[('Ollama '+str(i+1),url,'/api/tags') for i,url in enumerate(checked['ollama_urls'] or [checked['ollama_url']])]
                for name,url,route in targets:
                    try:
                        payload=comfy_client.api(url,route,timeout=5)
                        ok=isinstance(payload,dict) and (isinstance(payload.get('system'),dict) if route=='/system_stats' else isinstance(payload.get('models'),list))
                    except comfy_client.ComfyError:ok=False
                    results.append(dict(name=name,ok=ok))
                return jsonify(results=results)
            if request.method=='POST':return jsonify(editor.review(data.get('settings'),data.get('revision')))
            if not services.runner.busy.acquire(blocking=False):
                return jsonify(error='生成中は保存できません。完了後にもう一度確認してください。'),409
            try:return jsonify(editor.save(data.get('settings'),data.get('revision'),data.get('confirmation')))
            finally:services.runner.busy.release()
        except ConfigConflict as error:return jsonify(error=str(error)),409
        except (ValueError,TypeError,AttributeError):return jsonify(error='設定を検証できません。URL・数値・解析モデル・モデル系列・WD保存先と、設定ファイルの形式を確認してください。'),400
        except OSError:return jsonify(error='設定の読み書きに失敗しました。保存先の権限・容量を確認してください。'),503