from __future__ import annotations
from django.conf import settings
from django.db import models

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created at")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")

    class Meta:
        abstract = True

class AuditEvent(TimeStampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chakki_audit_events")
    action = models.CharField(max_length=80, verbose_name="Action")
    module = models.CharField(max_length=80, verbose_name="Module")
    object_reference = models.CharField(max_length=160, blank=True, verbose_name="Object reference")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Payload")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit event"
        verbose_name_plural = "Audit events"

    def __str__(self) -> str:
        return f"{self.module}: {self.action}"
