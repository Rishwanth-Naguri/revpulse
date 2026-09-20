import os
import json
import logging
import uuid
from typing import Dict, Any, Optional
import urllib.request
import urllib.error
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import get_migration_session

logger = logging.getLogger(__name__)

class AlertService:
    @staticmethod
    def send_slack_notification(webhook_url: str, message: str, title: str = "RevPulse Revenue Alert") -> bool:
        """
        Sends a rich Slack notification via Incoming Webhook.
        """
        if not webhook_url:
            return False

        payload = {
            "text": f"*{title}*\n{message}",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"⚡ {title}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Sent by *RevPulse* • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        }
                    ]
                }
            ]
        }

        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception as e:
            logger.error("Failed to deliver Slack webhook: %s", str(e))
            return False

    @staticmethod
    def send_email_notification(to_email: str, subject: str, body: str) -> bool:
        """
        Sends email notification via Resend API if RESEND_API_KEY is configured,
        or logs cleanly to console if in development.
        """
        resend_key = os.getenv("RESEND_API_KEY")
        if not resend_key:
            logger.info("[MOCK EMAIL] To: %s | Subject: %s | Body: %s", to_email, subject, body)
            return True

        try:
            payload = {
                "from": "RevPulse Alerts <alerts@revpulse.dev>",
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 201)
        except Exception as e:
            logger.error("Failed to send Resend email: %s", str(e))
            return False

    @staticmethod
    def check_and_dispatch_alerts(org_id: uuid.UUID) -> int:
        """
        Evaluates active alert rules for an organization and dispatches triggered alerts.
        Returns count of alerts fired.
        """
        with get_migration_session() as session:
            rules = session.execute(
                text("SELECT id, rule_type, threshold, channel, destination FROM alert_rules WHERE org_id = :org_id AND enabled = true"),
                {"org_id": str(org_id)}
            ).fetchall()

            if not rules:
                return 0

            fired = 0
            for r in rules:
                rule_id, rule_type, threshold, channel, destination = r
                triggered = False
                title = "RevPulse Alert"
                msg = ""

                if rule_type == "at_risk_threshold":
                    # Check if at-risk amount exceeds threshold
                    at_risk_res = session.execute(
                        text("SELECT COALESCE(SUM(amount_due_cents), 0) FROM invoices WHERE org_id = :org_id AND status IN ('open', 'uncollectible') AND period_end < NOW()"),
                        {"org_id": str(org_id)}
                    ).scalar() or 0
                    if (at_risk_res / 100) >= float(threshold or 1000):
                        triggered = True
                        title = "⚠️ High At-Risk Revenue Alert"
                        msg = f"At-risk overdue invoices have reached *${at_risk_res / 100:,.2f}*, exceeding your threshold of *${threshold}*."

                elif rule_type == "churn_spike":
                    # Check recent churn in past 7 days
                    churn_cents = session.execute(
                        text("SELECT COALESCE(SUM(amount_cents), 0) FROM mrr_movements WHERE org_id = :org_id AND movement_type = 'churn' AND date >= CURRENT_DATE - 7"),
                        {"org_id": str(org_id)}
                    ).scalar() or 0
                    if (churn_cents / 100) >= float(threshold or 500):
                        triggered = True
                        title = "🚨 Churn Spike Detected"
                        msg = f"Subscriptions churned in the last 7 days totaling *${churn_cents / 100:,.2f}* MRR."

                if triggered:
                    fired += 1
                    if channel == "slack" and destination:
                        AlertService.send_slack_notification(destination, msg, title)
                    elif channel == "email" and destination:
                        AlertService.send_email_notification(destination, title, msg)

                    # Log the alert
                    session.execute(
                        text("""
                        INSERT INTO alert_logs (id, org_id, rule_id, channel, payload, created_at)
                        VALUES (gen_random_uuid(), :org_id, :rule_id, :channel, :payload, NOW())
                        """),
                        {
                            "org_id": str(org_id),
                            "rule_id": str(rule_id),
                            "channel": channel,
                            "payload": json.dumps({"title": title, "message": msg}),
                        }
                    )
            session.commit()
            return fired
