"""Email-based password recovery pages."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.brand_pages import account_page, esc
from app.db import get_db
from app.services.password_recovery import issue_reset, recovery_origin, redeem_reset, send_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])

_REQUEST_COMPLETE = (
    "If an eligible account can receive recovery email, a link will arrive shortly. "
    "If you cannot recover your account by email, contact your installation operator."
)


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page():
    if not recovery_origin():
        return account_page(
            "Password recovery", "<p>Contact your installation operator to reset your password.</p>"
        )
    return account_page(
        "Forgot password?",
        """
<form method="post">
  <label for="email">Account email</label>
  <input id="email" name="email" type="email" autocomplete="email" required maxlength="320">
  <button type="submit">Send reset link</button>
</form>""",
    )


@router.post("/forgot-password", response_class=HTMLResponse)
def request_password_reset(
    background: BackgroundTasks, email: str = Form(..., max_length=320), db: Session = Depends(get_db)
):
    if (origin := recovery_origin()) and (issued := issue_reset(db, email)):
        address, token = issued
        background.add_task(send_reset_email, address, f"{origin}/auth/reset-password#{token}")
    return account_page("Check your email", f"<p>{_REQUEST_COMPLETE}</p>")


def _reset_form(message: str = "", *, status_code: int = 200, token: str = ""):
    # A rejected password can be retried without resending the email.
    return account_page(
        "Reset password",
        f"""
<p role="status" id="reset-message">{esc(message)}</p>
<form method="post">
  <input id="token" type="hidden" name="token" value="{esc(token)}">
  <label for="password">New password</label>
  <input id="password" name="password" type="password" autocomplete="new-password" required minlength="8" maxlength="72">
  <label for="confirm">Confirm password</label>
  <input id="confirm" name="confirm" type="password" autocomplete="new-password" required minlength="8" maxlength="72">
  <button id="submit-reset" type="submit" disabled>Reset password</button>
</form>
<script>
  const token = document.getElementById("token");
  const fragment = location.hash.slice(1);
  if (fragment) {{
    token.value = fragment;
    history.replaceState(null, "", location.pathname);
  }}
  if (token.value) document.getElementById("submit-reset").disabled = false;
  else document.getElementById("reset-message").textContent = "Open the link from your recovery email.";
</script>""",
        status_code=status_code,
    )


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page():
    return _reset_form()


@router.post("/reset-password", response_class=HTMLResponse)
def reset_password(
    token: str = Form(..., max_length=128),
    password: str = Form(..., max_length=72),
    confirm: str = Form(..., max_length=72),
    db: Session = Depends(get_db),
):
    if password != confirm:
        return _reset_form("The passwords do not match.", status_code=400, token=token)
    try:
        redeemed = redeem_reset(db, token, password)
    except ValueError as exc:
        return _reset_form(str(exc), status_code=400, token=token)
    if not redeemed:
        return account_page(
            "Reset link unavailable",
            '<p>This link is invalid or expired. <a href="/auth/forgot-password">Request a new link</a>.</p>',
            status_code=400,
        )
    response = account_page(
        "Password updated",
        '<p>Sign in using your new password. <a href="/dashboard">Open the dashboard</a> or return to your MCP client.</p>',
    )
    response.delete_cookie("nk_browser_session", httponly=True, samesite="lax")
    return response
