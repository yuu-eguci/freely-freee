"""freee 人事労務 API のラッパークライアントです。"""

from typing import Any

from app.clients.freee_api_client import ApiResponse, FreeeApiClient


class HrApiClient:
    """freee 人事労務 API のラッパーです。"""

    HR_BASE = "/hr/api/v1"

    def __init__(self, api_client: FreeeApiClient) -> None:
        self._client = api_client

    def get_current_user(self) -> ApiResponse:
        """ログインユーザー情報を取得します。"""

        return self._client.get(f"{self.HR_BASE}/users/me")

    def get_attendance_tags(self, employee_id: int, company_id: int) -> ApiResponse:
        """従業員の勤怠タグ一覧を取得します。"""

        return self._client.get(
            f"{self.HR_BASE}/employees/{employee_id}/attendance_tags",
            params={"company_id": company_id},
        )

    def get_work_record(self, employee_id: int, date: str, company_id: int) -> ApiResponse:
        """指定日の勤怠レコードを取得します。"""

        return self._client.get(
            f"{self.HR_BASE}/employees/{employee_id}/work_records/{date}",
            params={"company_id": company_id},
        )

    def get_paid_holidays(
        self,
        company_id: int,
        *,
        start_target_date: str,
        end_target_date: str,
        limit: int,
        offset: int,
    ) -> ApiResponse:
        """指定期間の有給申請一覧を取得します。"""

        return self._client.get(
            f"{self.HR_BASE}/approval_requests/paid_holidays",
            params={
                "company_id": company_id,
                "start_target_date": start_target_date,
                "end_target_date": end_target_date,
                "limit": limit,
                "offset": offset,
            },
        )

    def put_work_record(self, employee_id: int, date: str, body: "dict[str, Any]") -> ApiResponse:
        """指定日の勤怠レコードを更新します。"""

        return self._client.put(
            f"{self.HR_BASE}/employees/{employee_id}/work_records/{date}",
            json_body=body,
        )

    def put_attendance_tags(
        self, employee_id: int, date: str, body: "dict[str, Any]"
    ) -> ApiResponse:
        """指定日の勤怠タグを更新します。"""

        return self._client.put(
            f"{self.HR_BASE}/employees/{employee_id}/attendance_tags/{date}",
            json_body=body,
        )
