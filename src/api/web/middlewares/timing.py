import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..services.metrics_service import metrics_service


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Request ID correlation
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:10]
        request.state.request_id = request_id
        request.state.timings = {}

        t0 = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            dur_ms = (time.perf_counter() - t0) * 1000
            metrics_service.record_http_request(
                method=request.method,
                endpoint=request.url.path,
                status=500,
                duration_seconds=dur_ms / 1000.0,
            )
            raise

        dur_ms = (time.perf_counter() - t0) * 1000

        # 2. Record metrics
        metrics_service.record_http_request(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
            duration_seconds=dur_ms / 1000.0,
        )

        # 3. Server-Timing header construction
        timing_parts = [f"total;dur={dur_ms:.1f}"]
        timings: dict = getattr(request.state, "timings", {})
        for metric_name, metric_dur in timings.items():
            timing_parts.append(f"{metric_name};dur={metric_dur:.1f}")

        server_timing = ", ".join(timing_parts)

        # 4. Set headers
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = server_timing

        return response
