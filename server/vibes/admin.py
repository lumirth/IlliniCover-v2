from django.contrib import admin
from submissions.admin import ImmutableAdmin

from vibes.models import VibeObservation

admin.site.register(VibeObservation, ImmutableAdmin)
