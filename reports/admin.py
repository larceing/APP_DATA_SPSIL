from django.contrib import admin

from .models import Report, ReportPage


class ReportPageInline(admin.TabularInline):
    model = ReportPage
    extra = 1
    fields = ('title', 'order', 'visualization_type', 'data_source')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'active', 'order', 'updated_at')
    list_filter = ('active', 'allowed_groups')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('allowed_groups',)
    inlines = [ReportPageInline]


@admin.register(ReportPage)
class ReportPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'report', 'order', 'visualization_type', 'data_source')
    list_filter = ('visualization_type', 'report')
