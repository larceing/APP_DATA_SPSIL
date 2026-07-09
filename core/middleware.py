from .models import EnvironmentConfig


class EnvironmentMiddleware:
    """Expone el entorno activo (test/prod/demo) como request.environment."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.environment = EnvironmentConfig.load().current
        return self.get_response(request)
