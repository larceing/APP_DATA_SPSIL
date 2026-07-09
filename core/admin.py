from django.contrib import admin
from django.shortcuts import redirect

from .models import EnvironmentConfig, UIString


@admin.register(EnvironmentConfig)
class EnvironmentConfigAdmin(admin.ModelAdmin):
    list_display = ('current', 'updated_at', 'updated_by')
    change_form_template = 'admin/core/environmentconfig/change_form.html'

    def has_add_permission(self, request):
        return not EnvironmentConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ('current', 'updated_at', 'updated_by')

    def changelist_view(self, request, extra_context=None):
        config = EnvironmentConfig.load()
        return redirect('admin:core_environmentconfig_change', config.pk)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['environment_choices'] = EnvironmentConfig.Environment.choices
        extra_context['current_environment'] = EnvironmentConfig.load().current
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(UIString)
class UIStringAdmin(admin.ModelAdmin):
    list_display = ('key', 'es', 'it', 'en')
    search_fields = ('key', 'es', 'it', 'en', 'notes')
