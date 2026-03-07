"""alerts/notifier.py — Email + SMS alerts for high-value domain finds"""
import os
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Email config
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASS     = os.getenv("SMTP_PASS", "")
ALERT_EMAIL   = os.getenv("ALERT_EMAIL", "")

# SMS via Twilio (optional)
TWILIO_SID    = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN  = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM   = os.getenv("TWILIO_FROM", "")
ALERT_PHONE   = os.getenv("ALERT_PHONE", "")

fmt_k = lambda n: f"${n//1000}K" if n >= 1000 else f"${n}"

TYPE_EMOJI = {
    "unregistered": "🟢",
    "expiring":     "🟡",
    "aftermarket":  "🔵",
}


class Notifier:
    def send(self, hot_domains: list[dict]):
        """Send alerts via all configured channels"""
        if not hot_domains:
            return

        sent = False
        if SMTP_USER and ALERT_EMAIL:
            self._send_email(hot_domains)
            sent = True

        if TWILIO_SID and ALERT_PHONE:
            self._send_sms(hot_domains[:3])  # SMS: top 3 only
            sent = True

        if not sent:
            print("\n" + "🔥"*30)
            print("  ALERT: HIGH-VALUE DOMAINS FOUND (configure SMTP/Twilio for notifications)")
            for d in hot_domains:
                tag = TYPE_EMOJI.get(d.get("type",""), "⚪")
                print(f"  {tag} {d['domain']:<30} score={d['score']}  "
                      f"est={fmt_k(d['est_low'])}–{fmt_k(d['est_high'])}")
            print("🔥"*30 + "\n")

    def _send_email(self, domains: list[dict]):
        try:
            subject = f"🔥 AI Domain Bot: {len(domains)} HIGH-VALUE Finds — {datetime.now().strftime('%b %d %H:%M')}"

            # Build HTML email
            rows = ""
            for d in domains:
                tag   = TYPE_EMOJI.get(d.get("type",""), "⚪")
                color = "#22c55e" if d["score"] >= 90 else "#eab308"
                rows += f"""
                <tr>
                  <td style="padding:8px;border-bottom:1px solid #1e1e2e;font-family:monospace;color:#cdd6f4">{tag} {d['domain']}</td>
                  <td style="padding:8px;border-bottom:1px solid #1e1e2e;color:{color};font-weight:bold;text-align:center">{d['score']}</td>
                  <td style="padding:8px;border-bottom:1px solid #1e1e2e;color:#a6e3a1;text-align:center">{fmt_k(d['est_low'])}–{fmt_k(d['est_high'])}</td>
                  <td style="padding:8px;border-bottom:1px solid #1e1e2e;color:#89b4fa;text-align:center">{d.get('type','—')}</td>
                  <td style="padding:8px;border-bottom:1px solid #1e1e2e;text-align:center">
                    <a href="https://www.godaddy.com/domainsearch/find?domainToCheck={d['domain'].replace('.ai','')}&tld=ai"
                       style="color:#89dceb;text-decoration:none">Register →</a>
                  </td>
                </tr>"""

            html = f"""
            <html><body style="background:#1e1e2e;margin:0;padding:20px;font-family:sans-serif">
              <div style="max-width:700px;margin:0 auto">
                <h1 style="color:#cba6f7;font-size:24px;margin-bottom:4px">🤖 AI Domain Flip Bot</h1>
                <p style="color:#6c7086;margin-top:0">{datetime.now().strftime('%B %d, %Y at %H:%M')} — {len(domains)} domains above alert threshold</p>
                <table style="width:100%;border-collapse:collapse;background:#181825;border-radius:8px;overflow:hidden">
                  <thead>
                    <tr style="background:#313244">
                      <th style="padding:10px;color:#a6adc8;text-align:left">Domain</th>
                      <th style="padding:10px;color:#a6adc8">Score</th>
                      <th style="padding:10px;color:#a6adc8">Est. Value</th>
                      <th style="padding:10px;color:#a6adc8">Type</th>
                      <th style="padding:10px;color:#a6adc8">Action</th>
                    </tr>
                  </thead>
                  <tbody>{rows}</tbody>
                </table>
                <p style="color:#45475a;font-size:12px;margin-top:16px">
                  AI Domain Bot · running locally · <a href="#" style="color:#585b70">unsubscribe</a>
                </p>
              </div>
            </body></html>"""

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = SMTP_USER
            msg["To"]      = ALERT_EMAIL
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

            print(f"[ALERT] Email sent to {ALERT_EMAIL}")

        except Exception as e:
            print(f"[ALERT] Email failed: {e}")

    def _send_sms(self, domains: list[dict]):
        try:
            from twilio.rest import Client
            client = Client(TWILIO_SID, TWILIO_TOKEN)

            lines = [f"🔥 AI Domain Bot: {len(domains)} hot finds"]
            for d in domains[:3]:
                lines.append(f"• {d['domain']} (score {d['score']}, est {fmt_k(d['est_low'])}+)")

            body = "\n".join(lines)
            client.messages.create(body=body, from_=TWILIO_FROM, to=ALERT_PHONE)
            print(f"[ALERT] SMS sent to {ALERT_PHONE}")

        except ImportError:
            print("[ALERT] SMS skipped — install twilio: pip install twilio")
        except Exception as e:
            print(f"[ALERT] SMS failed: {e}")
