"""EDP W6 压测（EDP-033）：Admin/Analyst 双角色任务池 + 三档 VU stages。

用法（backend 目录；PYTHONUTF8=1 防 GBK 控制台下 locust 解析 pyproject 炸码，
--json 为 stdout 开关经重定向落盘）：
    PYTHONUTF8=1 uv run locust -f scripts/loadtest/locustfile.py --headless \
        --json > ../deploy/loadtest/locust.json --html ../deploy/loadtest/locust.html

env：EDP_API_BASE（缺省 http://localhost:8000；端口被占走 compose override 时
置 http://localhost:18000）、EDP_TENANT_SLUG（缺省 default）、EDP_ADMIN_USER /
EDP_ADMIN_PASS / EDP_ANALYST_USER / EDP_ANALYST_PASS（缺省 admin / analyst1 /
Admin@123!，seed 迁移 0005 缺省口令）、EDP_CASE_ID（缺省经 cases 列表取首条）。
EDP_LOCUST_STAGE="users,seconds" 单档运行（报告三档读数用）；缺省跑全三档
STAGES = (20,180),(50,180),(100,180)。

断言：全部请求 status_code < 500（catch_response 标 failure）。
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from locust import HttpUser, LoadTestShape, between, task

STAGES: tuple[tuple[int, int], ...] = ((20, 180), (50, 180), (100, 180))
API_BASE = os.getenv("EDP_API_BASE", "http://localhost:8000").rstrip("/")
TENANT_SLUG = os.getenv("EDP_TENANT_SLUG", "default")
ADMIN_USER = os.getenv("EDP_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("EDP_ADMIN_PASS", "Admin@123!")
ANALYST_USER = os.getenv("EDP_ANALYST_USER", "analyst1")
ANALYST_PASS = os.getenv("EDP_ANALYST_PASS", "Admin@123!")
CASE_ID = os.getenv("EDP_CASE_ID") or None


class StagesShape(LoadTestShape):
    """三档阶梯（20/50/100 VU 各 180s）；EDP_LOCUST_STAGE 单档覆盖。"""

    def tick(self):
        stages = STAGES
        if single := os.getenv("EDP_LOCUST_STAGE"):
            users, seconds = single.split(",")
            stages = ((int(users), int(seconds)),)
        elapsed = 0
        for users, seconds in stages:
            if self.get_run_time() < elapsed + seconds:
                return users, min(users, 10), None
            elapsed += seconds
        return None


class EdpUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2)
    host = API_BASE

    def on_start(self):
        creds = {
            "admin": (ADMIN_USER, ADMIN_PASS),
            "analyst1": (ANALYST_USER, ANALYST_PASS),
        }[self.role]
        with httpx.Client(base_url=API_BASE, timeout=10) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": creds[0],
                    "password": creds[1],
                    "tenant_slug": TENANT_SLUG,
                },
            )
            login.raise_for_status()
            self.headers = {
                "Authorization": f"Bearer {login.json()['access_token']}"
            }
            objects = client.get(
                "/api/v1/objects", params={"limit": 20}, headers=self.headers
            )
            objects.raise_for_status()
            self.object_ids = [item["object_id"] for item in objects.json()["items"]]
            if CASE_ID is None:
                cases = client.get(
                    "/api/v1/decisions/cases",
                    params={"limit": 1},
                    headers=self.headers,
                )
                cases.raise_for_status()
                self.case_id = cases.json()["items"][0]["case_id"]
            else:
                self.case_id = CASE_ID

    def _get(self, path: str, name: str, **params):
        with self.client.get(
            path, params=params, headers=self.headers, name=name, catch_response=True
        ) as response:
            if response.status_code >= 500:
                response.failure(f"HTTP {response.status_code}")

    @task(2)
    def health(self):
        self._get("/api/v1/health", "GET /api/v1/health")

    @task(3)
    def objects_list(self):
        self._get("/api/v1/objects", "GET /api/v1/objects?limit=20", limit=20)

    @task(3)
    def events_risk(self):
        with self.client.get(
            "/api/v1/events",
            params={"risk_level": "P1", "limit": 20},
            headers=self.headers,
            name="GET /api/v1/events?risk_level=P1",
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"HTTP {response.status_code}")
            elif cursor := response.json().get("next_cursor"):
                self._get(
                    "/api/v1/events",
                    "GET /api/v1/events?risk_level=P1",
                    risk_level="P1",
                    limit=20,
                    cursor=cursor,
                )

    @task(2)
    def tools_orders(self):
        self._get(
            "/api/v1/tools/orders", "GET /api/v1/tools/orders?limit=20", limit=20
        )

    @task(1)
    def case_detail(self):
        self._get(
            f"/api/v1/decisions/cases/{self.case_id}",
            "GET /api/v1/decisions/cases/{id}",
        )


class AdminUser(EdpUser):
    role = "admin"
    weight = 1

    @task(1)
    def quality_reports(self):
        self._get("/api/v1/admin/quality/reports", "GET /api/v1/admin/quality/reports")

    @task(1)
    def quality_coverage(self):
        self._get(
            "/api/v1/admin/quality/coverage", "GET /api/v1/admin/quality/coverage"
        )

    @task(1)
    def audit_logs(self):
        self._get("/api/v1/audit-logs", "GET /api/v1/audit-logs?limit=20", limit=20)

    @task(1)
    def events_batch(self):
        now = datetime.now(UTC)
        events = [
            {
                "event_type": "loadtest.activity",
                "object_id": random.choice(self.object_ids),
                "source_system": "loadtest",
                "occurred_at": (now + timedelta(microseconds=index)).isoformat(),
                "actor_type": "SERVICE",
                "data": {"run": "w6-loadtest", "seq": index},
            }
            for index in range(2)
        ]
        with self.client.post(
            "/api/v1/events/batch",
            json={"events": events},
            headers={**self.headers, "Idempotency-Key": str(uuid.uuid4())},
            name="POST /api/v1/events/batch",
            catch_response=True,
        ) as response:
            if response.status_code >= 500:
                response.failure(f"HTTP {response.status_code}")


class AnalystUser(EdpUser):
    role = "analyst1"
    weight = 1
