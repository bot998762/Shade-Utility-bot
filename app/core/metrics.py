from prometheus_client import Counter

class MetricsRegistry:
    def __init__(self):
        self.events_published = Counter("events_total", "Total domain events", ["event_type"])
        self.api_failures = Counter("api_failures_total", "External API failures", ["provider"])

metrics = MetricsRegistry()
