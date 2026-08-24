import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def generate_verification_code() -> str:
    """Generates a random 6-digit verification code."""
    return str(random.randint(100000, 999999))


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
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER_EMAIL, to_email, message.as_string())
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False