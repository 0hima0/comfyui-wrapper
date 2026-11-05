"""Register feature-specific routes without changing public endpoint names."""
from . import pages, batches, gallery, settings, history, models, jobs, installation, app_settings, recommendations

def register_routes(app, services):
    for module in (pages, batches, gallery, settings, history, models, jobs, installation, app_settings, recommendations):
        module.register(app, services)
