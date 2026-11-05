"""Read-only installed models page and explicit ComfyUI update checks."""
from flask import jsonify, render_template
from comfyui_wrapper.system.installation import inventory, check_update


def register(app, services):
    @app.get('/inventory')
    def inventory_page():
        return render_template('system.html', initial_tab='inventory')

    @app.get('/api/inventory')
    def installed_inventory():
        return jsonify(inventory(services))

    @app.get('/api/comfyui-update')
    def comfyui_update():
        return jsonify(check_update(services.runtime.comfy_url))