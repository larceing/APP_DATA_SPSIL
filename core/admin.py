from django.contrib import admin

from .models import UIString


@admin.register(UIString)
class UIStringAdmin(admin.ModelAdmin):
    list_display = ('key', 'es', 'zh', 'en')
    search_fields = ('key', 'es', 'zh', 'en', 'notes')
