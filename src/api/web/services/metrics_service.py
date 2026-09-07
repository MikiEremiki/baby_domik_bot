from collections import defaultdict
import threading
import time

class MetricsService:
    def __init__(self):
        self._lock = threading.Lock()
        # HTTP metrics
        # key: (method, endpoint, status) -> count
        self.http_requests_total = defaultdict(int)
        # key: (method, endpoint) -> list of durations in seconds
        self.http_durations = defaultdict(list)

        # YooKassa metrics
        # key: status ('success', 'timeout', 'error') -> count
        self.yookassa_requests_total = defaultdict(int)
        self.yookassa_durations = []

        # DB metrics
        self.db_durations = []

    def record_http_request(self, method: str, endpoint: str, status: int, duration_seconds: float):
        # Normalize endpoint to avoid high cardinality from IDs (e.g. /event/123 -> /event/{id})
        norm_endpoint = self._normalize_endpoint(endpoint)
        with self._lock:
            self.http_requests_total[(method.upper(), norm_endpoint, str(status))] += 1
            durations = self.http_durations[(method.upper(), norm_endpoint)]
            durations.append(duration_seconds)
            if len(durations) > 1000:
                self.http_durations[(method.upper(), norm_endpoint)] = durations[-1000:]

    def record_yookassa_call(self, status: str, duration_seconds: float):
        with self._lock:
            self.yookassa_requests_total[status] += 1
            self.yookassa_durations.append(duration_seconds)
            if len(self.yookassa_durations) > 1000:
                self.yookassa_durations = self.yookassa_durations[-1000:]

    def record_db_query(self, duration_seconds: float):
        with self._lock:
            self.db_durations.append(duration_seconds)
            if len(self.db_durations) > 1000:
                self.db_durations = self.db_durations[-1000:]

    def _normalize_endpoint(self, path: str) -> str:
        parts = path.strip('/').split('/')
        normalized = []
        for p in parts:
            if p.isdigit():
                normalized.append('{id}')
            else:
                normalized.append(p)
        return '/' + '/'.join(normalized) if normalized else '/'

    def generate_prometheus_metrics(self) -> str:
        lines = []
        lines.append("# HELP http_requests_total Total number of HTTP requests.")
        lines.append("# TYPE http_requests_total counter")
        with self._lock:
            for (method, endpoint, status), count in sorted(self.http_requests_total.items()):
                lines.append(f'http_requests_total{{method="{method}",endpoint="{endpoint}",status="{status}"}} {count}')

            lines.append("")
            lines.append("# HELP http_request_duration_seconds HTTP request duration in seconds.")
            lines.append("# TYPE http_request_duration_seconds summary")
            for (method, endpoint), durations in sorted(self.http_durations.items()):
                if durations:
                    count = len(durations)
                    total_sum = sum(durations)
                    sorted_d = sorted(durations)
                    p50 = sorted_d[int(count * 0.50)]
                    p90 = sorted_d[min(int(count * 0.90), count - 1)]
                    p99 = sorted_d[min(int(count * 0.99), count - 1)]
                    lines.append(f'http_request_duration_seconds{{method="{method}",endpoint="{endpoint}",quantile="0.5"}} {p50:.6f}')
                    lines.append(f'http_request_duration_seconds{{method="{method}",endpoint="{endpoint}",quantile="0.9"}} {p90:.6f}')
                    lines.append(f'http_request_duration_seconds{{method="{method}",endpoint="{endpoint}",quantile="0.99"}} {p99:.6f}')
                    lines.append(f'http_request_duration_seconds_sum{{method="{method}",endpoint="{endpoint}"}} {total_sum:.6f}')
                    lines.append(f'http_request_duration_seconds_count{{method="{method}",endpoint="{endpoint}"}} {count}')

            lines.append("")
            lines.append("# HELP yookassa_requests_total Total number of YooKassa API calls.")
            lines.append("# TYPE yookassa_requests_total counter")
            for status in ['success', 'timeout', 'error']:
                cnt = self.yookassa_requests_total[status]
                lines.append(f'yookassa_requests_total{{status="{status}"}} {cnt}')

            lines.append("")
            lines.append("# HELP yookassa_request_duration_seconds YooKassa API request duration in seconds.")
            lines.append("# TYPE yookassa_request_duration_seconds summary")
            if self.yookassa_durations:
                cnt = len(self.yookassa_durations)
                total_sum = sum(self.yookassa_durations)
                sorted_d = sorted(self.yookassa_durations)
                p50 = sorted_d[int(cnt * 0.50)]
                p95 = sorted_d[min(int(cnt * 0.95), cnt - 1)]
                lines.append(f'yookassa_request_duration_seconds{{quantile="0.5"}} {p50:.6f}')
                lines.append(f'yookassa_request_duration_seconds{{quantile="0.95"}} {p95:.6f}')
                lines.append(f'yookassa_request_duration_seconds_sum {total_sum:.6f}')
                lines.append(f'yookassa_request_duration_seconds_count {cnt}')
            else:
                lines.append('yookassa_request_duration_seconds_count 0')
                lines.append('yookassa_request_duration_seconds_sum 0.0')

            lines.append("")
            lines.append("# HELP db_query_duration_seconds Database query duration in seconds.")
            lines.append("# TYPE db_query_duration_seconds summary")
            if self.db_durations:
                cnt = len(self.db_durations)
                total_sum = sum(self.db_durations)
                lines.append(f'db_query_duration_seconds_sum {total_sum:.6f}')
                lines.append(f'db_query_duration_seconds_count {cnt}')
            else:
                lines.append('db_query_duration_seconds_count 0')
                lines.append('db_query_duration_seconds_sum 0.0')

        lines.append("")
        return "\n".join(lines)

metrics_service = MetricsService()
