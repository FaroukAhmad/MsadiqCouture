import smtplib
import urllib.parse
import urllib.request
import base64
from email.message import EmailMessage


class NotificationService:
    def __init__(self, config):
        self.config = config

    def email(self, recipient, subject, body):
        if not self.config["SMTP_HOST"]:
            return False
        message = EmailMessage()
        message["From"] = self.config["MAIL_FROM"]
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.config["SMTP_HOST"], self.config["SMTP_PORT"], timeout=15) as server:
            server.starttls()
            if self.config["SMTP_USERNAME"]:
                server.login(self.config["SMTP_USERNAME"], self.config["SMTP_PASSWORD"])
            server.send_message(message)
        return True

    def sms(self, recipient, body):
        sid = self.config["TWILIO_ACCOUNT_SID"]
        token = self.config["TWILIO_AUTH_TOKEN"]
        sender = self.config["TWILIO_FROM_NUMBER"]
        if not sid or not token or not sender:
            return False
        payload = urllib.parse.urlencode({"To": recipient, "From": sender, "Body": body}).encode()
        credentials = base64.b64encode(f"{sid}:{token}".encode()).decode()
        request = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=payload,
            headers={"Authorization": f"Basic {credentials}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15):
            return True
