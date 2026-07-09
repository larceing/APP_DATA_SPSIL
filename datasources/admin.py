from django.contrib import admin

from .models import DataSource, ImportedRow


class ImportedRowInline(admin.TabularInline):
    model = ImportedRow
    extra = 0
    fields = ('row_number', 'data', 'imported_at')
    readonly_fields = ('row_number', 'data', 'imported_at')
    can_delete = False
    max_num = 20

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_table', 'environment', 'active', 'last_imported_at')
    list_filter = ('environment', 'active')
    search_fields = ('name', 'target_table')
    readonly_fields = ('last_imported_at',)
    inlines = [ImportedRowInline]


@admin.register(ImportedRow)
class ImportedRowAdmin(admin.ModelAdmin):
    list_display = ('data_source', 'row_number', 'imported_at')
    list_filter = ('data_source',)
