"""Email service using Resend for sending verification and invitation emails."""

import os
import resend
from typing import Optional

# Initialize Resend
resend.api_key = os.getenv('RESEND_API_KEY')

# Get sender email from environment (must be verified in Resend)
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'noreply@yourdomain.com')
APP_NAME = "Philosophers Fridge"


def send_verification_email(to_email: str, name: str, verification_link: str) -> bool:
    """Send email verification link to new user."""
    try:
        params = {
            "from": f"{APP_NAME} <{SENDER_EMAIL}>",
            "to": [to_email],
            "subject": f"Verify your email for {APP_NAME}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #3273dc;">Welcome to {APP_NAME}!</h2>
                <p>Hi {name},</p>
                <p>Thanks for signing up! Please verify your email address by clicking the button below:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{verification_link}" 
                       style="background-color: #3273dc; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 4px; display: inline-block;">
                        Verify Email
                    </a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{verification_link}</p>
                <p>This link will expire in 24 hours.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #888; font-size: 12px;">
                    If you didn't create an account, you can safely ignore this email.
                </p>
            </div>
            """
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        return False


def send_password_reset_email(to_email: str, name: str, reset_link: str) -> bool:
    """Send password reset link to user."""
    try:
        params = {
            "from": f"{APP_NAME} <{SENDER_EMAIL}>",
            "to": [to_email],
            "subject": f"Reset your password for {APP_NAME}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #3273dc;">Password Reset Request</h2>
                <p>Hi {name},</p>
                <p>We received a request to reset your password. Click the button below to create a new password:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" 
                       style="background-color: #3273dc; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 4px; display: inline-block;">
                        Reset Password
                    </a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{reset_link}</p>
                <p>This link will expire in 1 hour.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #888; font-size: 12px;">
                    If you didn't request a password reset, you can safely ignore this email.
                </p>
            </div>
            """
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Failed to send password reset email: {e}")
        return False


def send_household_invitation_email(
    to_email: str, 
    inviter_name: str, 
    household_name: str, 
    invitation_link: str
) -> bool:
    """Send household invitation email."""
    try:
        params = {
            "from": f"{APP_NAME} <{SENDER_EMAIL}>",
            "to": [to_email],
            "subject": f"You've been invited to join {household_name} on {APP_NAME}",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #3273dc;">You're Invited!</h2>
                <p>Hi there,</p>
                <p><strong>{inviter_name}</strong> has invited you to join the household 
                   <strong>"{household_name}"</strong> on {APP_NAME}.</p>
                <p>{APP_NAME} helps you track meals and nutrition for your household.</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{invitation_link}" 
                       style="background-color: #48c774; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 4px; display: inline-block;">
                        Accept Invitation
                    </a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{invitation_link}</p>
                <p>This invitation will expire in 7 days.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
                <p style="color: #888; font-size: 12px;">
                    If you don't know {inviter_name}, you can safely ignore this email.
                </p>
            </div>
            """
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Failed to send invitation email: {e}")
        return False
