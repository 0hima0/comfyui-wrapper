"""User-managed recommendations never silently alter a generation request."""
from flask import jsonify,request
from comfyui_wrapper.infrastructure.http_support import require_ui_request
from comfyui_wrapper.settings.recommendations import RecommendationStore

def register(app,services):
    store=RecommendationStore(services.history)
    @app.route('/api/recommendations',methods=['GET','PUT','DELETE'])
    def recommendations():
        if request.method!='GET':require_ui_request()
        data=request.args if request.method=='GET' else request.get_json(silent=True)
        try:
            if not isinstance(data,dict) and request.method!='GET':raise ValueError('入力形式が不正です。')
            kind,name=data.get('kind'),data.get('name')
            if request.method=='PUT':return jsonify(values=store.save(kind,name,data.get('values')))
            if request.method=='DELETE':store.delete(kind,name);return jsonify(deleted=True)
            return jsonify(values=store.get(kind,name))
        except ValueError as error:return jsonify(error=str(error)),400
