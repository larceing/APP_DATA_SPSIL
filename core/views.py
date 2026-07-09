from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .models import EnvironmentConfig


@staff_member_required
@require_POST
def switch_environment(request):
    target = request.POST.get('environment')
    valid_values = dict(EnvironmentConfig.Environment.choices)

    if target not in valid_values:
        messages.error(request, 'Entorno no válido.')
    else:
        config = EnvironmentConfig.load()
        config.current = target
        config.updated_by = request.user
        config.save()
        messages.success(request, f'Entorno cambiado a: {valid_values[target]}.')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/admin/'
    return redirect(next_url)
