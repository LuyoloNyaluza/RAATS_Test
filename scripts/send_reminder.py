#!/usr/bin/env python3
import smtplib
import ssl
from email.message import EmailMessage

def send_reminder():
    smtp_server = "mail.1stopmuzic.com"
    smtp_port = 465  # SSL
    sender_email = "luyolon@1stopmuzic.com"
    password = "1Stop@2014"
    receiver_email = "luyolon@1stopmuzic.com"

    msg = EmailMessage()
    msg["Subject"] = "RAATS Weekly Reminder"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg.set_content(
        """Reminder: Review RAATS weekly plan and log progress.

Check your repository and update your journal for the week.

Best,
RAATS Bot"""
    )

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
        server.login(sender_email, password)
        server.send_message(msg)
    print("Reminder email sent to", receiver_email)

if __name__ == "__main__":
    send_reminder()