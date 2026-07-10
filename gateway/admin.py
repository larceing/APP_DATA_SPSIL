import secrets

from django.contrib import admin, messages

from .consumers import CONNECTED_NODES
from .models import GatewayNode


@admin.register(GatewayNode)
class GatewayNodeAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'active', 'is_connected', 'last_connected_at')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('last_connected_at', 'created_at')
    actions = ['regenerate_token']

    @admin.display(boolean=True, description='Conectado')
    def is_connected(self, obj):
        return obj.slug in CONNECTED_NODES

    def save_model(self, request, obj, form, change):
        raw_token = None
        if not obj.pk or not obj.token_hash:
            raw_token = secrets.token_hex(32)
            obj.set_token(raw_token)
        super().save_model(request, obj, form, change)
        if raw_token:
            messages.warning(
                request,
                f'Token generado para "{obj.name}" (guárdalo ya, no volverá a mostrarse): {raw_token}',
            )

    @admin.action(description='Regenerar token (revoca el actual)')
    def regenerate_token(self, request, queryset):
        for node in queryset:
            raw_token = secrets.token_hex(32)
            node.set_token(raw_token)
            node.save(update_fields=['token_hash'])
            messages.warning(request, f'Nuevo token para "{node.name}": {raw_token}')
