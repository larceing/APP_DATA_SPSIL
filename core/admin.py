from django.contrib import admin

from .models import UIString


@admin.register(UIString)
class UIStringAdmin(admin.ModelAdmin):
    list_display = ('key', 'es', 'it', 'en')
    search_fields = ('key', 'es', 'it', 'en', 'notes')
