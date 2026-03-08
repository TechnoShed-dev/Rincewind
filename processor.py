"""
Filename: processor.py
Project: Rincewind Universal Email Gateway
Version: 2.4.0
Description: Unified traffic cop for TechnoShed email services. 
             Handles multi-format translations (DOCX/PDF), automated 
             uploads, and language-aware global help.
"""

import os
import sys
import time
import re
import logging
import imaplib
import email
import smtplib
import qrcode
from io import BytesIO
from logging.handlers import RotatingFileHandler
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from google.cloud import translate_v3 as translate

# --- GCP CONFIGURATION ---
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'technoshed-translator')
LOCATION = "global"

# --- LOGGING SETUP ---
LOG_FILE = '/app/uploader.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=1024*1024, backupCount=3),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- ENVIRONMENT VARIABLES ---
GMX_USER = os.environ.get('GMX_USER')
GMX_PASS = os.environ.get('GMX_PASS')
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASS = os.environ.get('SMTP_PASS')
SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
BASE_PUBLIC_URL = os.environ.get('BASE_PUBLIC_URL')
UPLOAD_DIR = os.environ.get('UPLOAD_DIR')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL_SECONDS', 300))

# Initialize Google Translate
client = translate.TranslationServiceClient()
parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"

# --- HELPER FUNCTIONS ---

def verify_connections():
    """Confirms all external services are reachable at startup."""
    logging.info("--- Starting System Heartbeat ---")
    try:
        client.detect_language(content="heartbeat", parent=parent)
        logging.info("✅ GCP Translate: Connection Verified.")
    except Exception as e:
        logging.error(f"❌ GCP Translate: Verification Failed - {e}")

    try:
        with imaplib.IMAP4_SSL('imap.gmx.com') as M:
            M.login(GMX_USER, GMX_PASS)
            logging.info("✅ GMX IMAP: Authentication Successful.")
    except Exception as e:
        logging.error(f"❌ GMX IMAP: Authentication Failed - {e}")

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            logging.info("✅ SMTP2GO: Authentication Successful.")
    except Exception as e:
        logging.error(f"❌ SMTP2GO: Authentication Failed - {e}")
    logging.info("--- Heartbeat Complete ---\n")

def sanitize_path(path):
    """Strips illegal characters and prevents directory traversal."""
    if not path: return ""
    path = path.strip()
    path = re.sub(r'[\\|:*"<>?]', '', path)
    return path.replace('..', '').replace('/', os.sep).replace('\\', os.sep).strip(os.sep)

def generate_qr_code(url):
    """Generates a QR code image in memory."""
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer.getvalue()
    except Exception as e:
        logging.error(f"Error generating QR code: {e}")
        return None

def extract_valid_attachments(msg):
    """Generator that yields (safe_filename, raw_bytes) for valid attachments."""
    for part in msg.walk():
        if part.get_content_disposition() != 'attachment':
            continue
        raw_filename = part.get_filename()
        if raw_filename:
            filename, encoding = email.header.decode_header(raw_filename)[0]
            if isinstance(filename, bytes):
                try: filename = filename.decode(encoding or 'utf-8', errors='ignore')
                except: filename = raw_filename
            safe_filename = sanitize_path(filename)
            if safe_filename:
                yield safe_filename, part.get_payload(decode=True)

def extract_body(msg):
    """Extracts the plain text body from the email."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors='ignore')
    else:
        return msg.get_payload(decode=True).decode(errors='ignore')
    return ""

def send_universal_reply(recipient, status, subject_prefix, text_content, html_content, attachments=None):
    """Sends consistent replies for all services."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"{subject_prefix}: {status}"
    msg['From'] = f"TechnoShed Services <{SMTP_USER}>"
    msg['To'] = recipient
    msg.attach(MIMEText(text_content, 'plain'))
    msg.attach(MIMEText(html_content, 'html'))

    if attachments:
        for filename, file_bytes, maintype, subtype in attachments:
            part = MIMEBase(maintype, subtype)
            part.set_payload(file_bytes)
            email.encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipient, msg.as_string())
        logging.info(f"Reply sent to {recipient}")
    except Exception as e:
        logging.error(f"SMTP Error: {e}")

# --- SERVICE MODULES ---

def handle_file_upload(msg, sender, subject):
    """Handles file hosting and QR generation."""
    relative_path = sanitize_path(subject)
    destination_folder = os.path.join(UPLOAD_DIR, relative_path)
    os.makedirs(destination_folder, exist_ok=True)
    
    processed = 0
    for filename, raw_bytes in extract_valid_attachments(msg):
        filepath = os.path.join(destination_folder, filename)
        try:
            with open(filepath, 'wb') as fp:
                fp.write(raw_bytes)
            
            final_url = f"{BASE_PUBLIC_URL}/{relative_path.replace(os.sep, '/')}/{filename}"
            qr_bytes = generate_qr_code(final_url)
            
            html = f"<h2>✅ Upload Successful!</h2><p>File <strong>{filename}</strong> uploaded.</p><p>Link: <a href='{final_url}'>{final_url}</a></p>"
            attachments = [("QR_Code.png", qr_bytes, 'image', 'png')] if qr_bytes else []
            send_universal_reply(sender, "SUCCESS", "File Upload", f"Uploaded: {final_url}", html, attachments)
            processed += 1
        except Exception as e:
            logging.error(f"Save failed for {filename}: {e}")

    if processed == 0:
        send_universal_reply(sender, "FAILED", "File Upload", "No attachments found.", "<h2>❌ Upload Failed</h2><p>No valid files attached.</p>")

def handle_translation(msg, sender, subject, body):
    """Handles DOCX/PDF and Plain Text Translation."""
    target_code = "ro"
    lang_map = {"polish": "pl", "lithuanian": "lt", "bulgarian": "bg", "spanish": "es"}
    if subject and subject.strip().lower() in lang_map:
        target_code = lang_map[subject.strip().lower()]

    processed = 0
    
    for filename, raw_bytes in extract_valid_attachments(msg):
        ext = os.path.splitext(filename.lower())[1]
        mime_types = {
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.pdf': 'application/pdf'
        }
        
        if ext in mime_types:
            try:
                response = client.translate_document(
                    request={
                        "parent": parent,
                        "target_language_code": target_code,
                        "document_input_config": {"content": raw_bytes, "mime_type": mime_types[ext]},
                    }
                )
                translated_bytes = response.document_translation.byte_stream_outputs[0]
                new_filename = filename.replace(ext, f'_{target_code.upper()}{ext}')
                
                send_universal_reply(
                    sender, "SUCCESS", "Translation", 
                    f"Translated {filename}", 
                    f"<h2>✅ Done</h2><p>Attached is your {target_code.upper()} version.</p>",
                    [(new_filename, translated_bytes, 'application', 'octet-stream')]
                )
                processed += 1
            except Exception as e:
                logging.error(f"Doc Error: {e}")

    if processed == 0 and body.strip():
        try:
            resp = client.translate_text(contents=[body], target_language_code=target_code, parent=parent)
            translation = resp.translations[0].translated_text
            send_universal_reply(sender, "SUCCESS", "Text Translation", translation, f"<p>{translation}</p>")
            processed += 1
        except Exception as e:
            logging.error(f"Text Error: {e}")

    if processed == 0:
        send_universal_reply(sender, "FAILED", "Translation", "No valid content.", "Please attach a .docx/.pdf or type text.")

def handle_help(to_addr, body, sender):
    """Bilingual Help Desk."""
    help_content = "TechnoShed Translation: Use Subject for language. Attach .docx, .pdf or type in body."
    if "uploads" in to_addr:
        help_content = "TechnoShed Uploads: Attach files to host them and receive a QR code."
    
    send_universal_reply(sender, "HELP", "System Manual", help_content, f"<h2>Guide</h2><p>{help_content}</p>")

# --- CORE ENGINE ---

def check_mail():
    try:
        with imaplib.IMAP4_SSL('imap.gmx.com') as M:
            M.login(GMX_USER, GMX_PASS)
            M.select('INBOX')
            _, data = M.search(None, 'UNSEEN')
            for num in data[0].split():
                _, msg_data = M.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(msg_data[0][1])
                
                sender = email.utils.parseaddr(msg['from'])[1]
                subject = (msg.get('Subject') or "").strip()
                to_addr = email.utils.parseaddr(msg.get('To'))[1].lower()
                body = extract_body(msg)
                
                # Fixed: Use a generator check to see if attachments exist [cite: 1, 5]
                has_attachments = any(extract_valid_attachments(msg))

                if not subject and not body and not has_attachments:
                    M.store(num, '+FLAGS', '\\Seen')
                    continue

                if "help" in subject.lower():
                    handle_help(to_addr, body, sender)
                elif "translations@" in to_addr:
                    handle_translation(msg, sender, subject, body)
                elif "uploads@" in to_addr:
                    handle_file_upload(msg, sender, subject)

                M.store(num, '+FLAGS', '\\Seen')
        logging.info(f"Polling complete. Sleeping {POLL_INTERVAL}s.")
    except Exception as e:
        logging.error(f"IMAP Loop Error: {e}")

if __name__ == "__main__":
    logging.info(f"Rincewind v2.4.0 Online. Project: {PROJECT_ID}")
    verify_connections()
    while True:
        check_mail()
        time.sleep(POLL_INTERVAL)