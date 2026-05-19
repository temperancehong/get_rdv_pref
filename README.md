# RDV Préfecture Slot Monitor

Monitors the three Palaiseau `remise de titre` RDV Préfecture guichets and emails
you when new appointment slots are detected.

By default, CAPTCHA/security-code challenges stay fully manual. Optional local
OCR assistance can suggest or fill a candidate code, but the browser stays
visible and waits for you to review and continue.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Optional OCR assistance:

```bash
git submodule update --init --recursive
pip install -r requirements-ocr.txt
```

Edit `.env` and set your Gmail address plus a Gmail App Password:

```env
SMTP_USER=your_gmail@gmail.com
SMTP_APP_PASSWORD=your_16_character_app_password
ALERT_TO=recipient@example.com
```

For Gmail, create an App Password from your Google Account security settings.
Do not use your normal Gmail password.

## Run

Check once:

```bash
python rdv_monitor.py --once
```

Run continuously every 30 minutes:

```bash
python rdv_monitor.py
```

Test email rendering without sending:

```bash
python rdv_monitor.py --once --dry-run-email
```

Run once with OCR-assisted security-code fill:

```bash
python rdv_monitor.py --once --captcha-ocr-mode fill
```

Run once with manual CAPTCHA plus Telegram alert:

```bash
python rdv_monitor.py --once --captcha-ocr-mode off --telegram-captcha-alert
```

## How It Works

- Opens a visible Chromium browser with a persistent profile in
  `.playwright-profile`.
- Checks these Palaiseau démarches:
  - `2246`
  - `2282`
  - `2283`
- Navigates toward the `creneau` page.
- Waits 30 seconds between Palaiseau démarches by default.
- If a security code appears, optionally screenshots the CAPTCHA image, runs
  local OCR, and either prints or fills the candidate code.
- If Telegram alerts are enabled, sends a message asking you to type the
  security code in the visible browser.
- The script does not submit the security-code form; you review and click
  `Suivant`.
- If a block/error page is detected, stops the current check and backs off for
  about 120 minutes before retrying in continuous mode.
- Extracts visible appointment labels containing times.
- Sends one email for newly detected slots.
- Saves alerted slot IDs in `seen_slots.json` to avoid duplicate emails.

## Notes

- Keep the browser visible because the security-code step requires manual review.
- The script checks availability only. It does not book, confirm, or cancel an
  appointment.
- If the prefecture site changes its wording or markup, the slot parser may need
  a small update.
