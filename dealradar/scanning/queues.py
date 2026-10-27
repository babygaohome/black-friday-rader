"""Celery queue names, shared by the worker config and the admin queue-length view."""
QUEUE_NAMES = ("scan.high", "scan.normal", "scan.low", "alert.high", "alert.normal", "notification", "maintenance")
