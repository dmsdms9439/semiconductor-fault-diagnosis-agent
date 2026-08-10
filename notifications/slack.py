import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Slack block 하나의 text 필드 상한은 3000자. LLM 원인분석이 길어지면
# invalid_blocks 로 알림 전체가 실패하므로 여유를 두고 자른다.
_TEXT_LIMIT = 2800

_STATUS_ICON = {"High": "🔴", "Low": "🔵", "Normal": "⚪"}


def _truncate(text: str, limit: int = _TEXT_LIMIT) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …(이하 생략)"


def _format_shap_lines(shap_analysis) -> str:
    """
    SHAPExplainer.explain() 결과(list of dict)를 Slack mrkdwn 라인으로 변환.

    각 항목 키: sensor, shap_value, current_value, mean_value,
                normal_range[lo, hi], status, direction
    """
    lines = []
    for i, item in enumerate(shap_analysis, 1):
        if not isinstance(item, dict):
            continue
        sensor = item.get("sensor", "unknown")
        status = item.get("status", "Normal")
        icon = _STATUS_ICON.get(status, "⚪")
        shap_val = item.get("shap_value", 0.0)
        current = item.get("current_value", 0.0)
        mean = item.get("mean_value", 0.0)
        rng = item.get("normal_range") or [0.0, 0.0]

        # stats 파일이 없으면 normal_range 가 [0, 0] 으로 오므로 그때는 범위를 숨긴다.
        if len(rng) >= 2 and (rng[0] or rng[1]):
            ctx = f"정상 평균 `{mean}`, 범위 `{rng[0]} ~ {rng[1]}`"
        else:
            ctx = f"정상 평균 `{mean}`"

        lines.append(
            f"{i}. {icon} *{sensor}* [{status}]\n"
            f"     현재 `{current}` · {ctx} · SHAP `{shap_val:+.4f}`"
        )
    if not lines:
        return ""
    return "*🔬 SHAP 주요 기여 센서 (Top %d)*\n" % len(lines) + "\n".join(lines)


class SlackNotifier:
    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    def send_alert(self, fault_name, run_name, mse, confidence, explanation=None,
                   shap_analysis=None, recommendation=None):
        """
        Sends a formatted alert to Slack

        shap_analysis: SHAPExplainer.explain() 의 반환 리스트. 주면 기여 센서
                       Top-N(값/정상범위/High·Low/SHAP 부호)을 별도 섹션으로 첨부한다.
        recommendation: GraphRAG 정비 가이드 텍스트(있으면 첨부).
        """
        if not self.webhook_url:
            print("⚠️ [Slack] No webhook URL found in .env. Skipping alert.")
            return

        payload = {
            "username": "Semiconductor Guardian",
            "icon_emoji": ":shield:",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 Anomaly Detected: " + fault_name,
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Run ID:*\n{run_name}"},
                        {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.2f}"},
                        {"type": "mrkdwn", "text": f"*MSE Score:*\n{mse:.4f}"},
                        {"type": "mrkdwn", "text": f"*Status:*\n{fault_name}"}
                    ]
                }
            ]
        }

        # --- SHAP 기여도 섹션 ---
        if shap_analysis:
            shap_text = _format_shap_lines(shap_analysis)
            if shap_text:
                payload["blocks"].append({"type": "divider"})
                payload["blocks"].append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": _truncate(shap_text)}
                })

        if explanation:
            payload["blocks"].append({"type": "divider"})
            payload["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _truncate(f"*🧠 AI 원인 분석:*\n{explanation}")
                }
            })

        if recommendation:
            payload["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _truncate(f"*🛠️ 정비 가이드:*\n{recommendation}")
                }
            })

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code != 200:
                print(f"❌ [Slack] Failed to send alert: {response.status_code}, {response.text}")
            else:
                print(f"✅ [Slack] Alert sent for {run_name}")
        except Exception as e:
            print(f"❌ [Slack] Error sending alert: {e}")

    def send_daily_summary(self, report_text: str):
        """
        일일 모니터링 요약 리포트를 Slack에 전송 (Airflow DAG에서 호출).

        report_text: dags/report_utils.build_report()가 만든 완성된 멀티라인 문자열.
        """
        if not self.webhook_url:
            print("⚠️ [Slack] No webhook URL found in .env. Skipping daily summary.")
            return False

        payload = {
            "username": "Semiconductor Guardian",
            "icon_emoji": ":bar_chart:",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": report_text}
                }
            ]
        }
        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code != 200:
                print(f"❌ [Slack] Daily summary failed: {response.status_code}, {response.text}")
                return False
            print("✅ [Slack] Daily summary sent.")
            return True
        except Exception as e:
            print(f"❌ [Slack] Error sending daily summary: {e}")
            return False

if __name__ == "__main__":
    # Test (requires SLACK_WEBHOOK_URL in .env)
    notifier = SlackNotifier()
    notifier.send_alert("UNKNOWN FAULT", "RUN_TEST_001", 0.85, 0.45, "This is a test explanation.")
