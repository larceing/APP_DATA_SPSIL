import secrets

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .consumers import CONNECTED_NODES
from .models import Department, ExclusionRule, GatewayNode, Page, SupplierCategory, UserProfile


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


@admin.register(ExclusionRule)
class ExclusionRuleAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'valor', 'activo', 'created_at')
    list_filter = ('tipo', 'activo')
    search_fields = ('valor',)


@admin.register(SupplierCategory)
class SupplierCategoryAdmin(admin.ModelAdmin):
    list_display = ('codpro', 'organizacion', 'categoria', 'activo')
    list_filter = ('categoria', 'activo')
    search_fields = ('codpro', 'organizacion')


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'group_label', 'url_name', 'order')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    filter_horizontal = ('pages',)


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    filter_horizontal = ('extra_pages',)
    fk_name = 'user'


class UserAdmin(DjangoUserAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), UserAdmin)
