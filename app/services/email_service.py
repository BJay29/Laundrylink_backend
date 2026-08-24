import os
import random
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def generate_verification_code() -> str:
    """Generates a random 6-digit verification code."""
    return str(random.randint(100000, 999999))


def _connect_smtp() -> smtplib.SMTP:
    """
    Connects to Gmail's SMTP server using an explicit IPv4 address.
    Render's network does not support outbound IPv6, which causes
    'OSError: [Errno 101] Network is unreachable' if the hostname
    resolves to an IPv6 address by default.
    """
    ipv4_address = socket.gethostbyname(SMTP_SERVER)
    server = smtplib.SMTP(ipv4_address, SMTP_PORT, timeout=15)
    server.ehlo(SMTP_SERVER)  # Gmail expects the real hostname in EHLO, not the raw IP
    server.starttls()
    server.ehlo(SMTP_SERVER)
    return server


def send_verification_email(to_email: str, full_name: str, code: str) -> bool:
    """
    Sends a 6-digit verification code to the customer's email via Gmail SMTP.
    Returns True if the email was sent successfully, False otherwise.
    """
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        print("Email service not configured: missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD in .env")
        return False

    subject = "Verify your LaundryLink account"
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #12315E;">Welcome to LaundryLink, {full_name}!</h2>
        <p style="color: #66809E;">Use the code below to verify your account:</p>
        <div style="background: #F4F7FB; padding: 20px; border-radius: 12px; text-align: center; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1769E0;">{code}</span>
        </div>
        <p style="color: #66809E; font-size: 13px;">This code will expire in 10 minutes. If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"LaundryLink <{GMAIL_SENDER_EMAIL}>"
    message["To"] = to_email
    message.attach(MIMEText(body, "html"))

    try:
        server = _connect_smtp()
        server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER_EMAIL, to_email, message.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False


def debug_send_email(to_email: str) -> dict:
    """
    TEMPORARY DEBUG: Same as send_verification_email but returns the
    actual exception message instead of just True/False. Remove this
    function once the email delivery issue is resolved.
    """
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        return {"success": False, "error": "Missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD"}

    message = MIMEMultipart("alternative")
    message["Subject"] = "LaundryLink Debug Test"
    message["From"] = f"LaundryLink <{GMAIL_SENDER_EMAIL}>"
    message["To"] = to_email
    message.attach(MIMEText("<p>This is a debug test email.</p>", "html"))

    try:
        server = _connect_smtp()
        server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_SENDER_EMAIL, to_email, message.as_string())
        server.quit()
        return {"success": True, "error": None}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}