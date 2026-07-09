from .models import EnvironmentConfig


def environment(request):
    return {'current_environment': EnvironmentConfig.load().current}
