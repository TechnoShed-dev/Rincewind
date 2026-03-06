# Filename: processor.py
# Version: 2.0.0

import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
import email.header
import os
import time
import re
import smtplib
import qrcode
from io import BytesIO
import logging
from logging.handlers import RotatingFileHandler

from PIL import Image
from google.cloud import translate_v3 as translate

# 🌟 LOGGING CONFIGURATION 🌟
import sys # Add this if it isn't already in your imports

LOG_FILE_CONTAINER_PATH = '/app/uploader.log'

# 1. The File Logger (Keeps a permanent record inside the container)
file_handler = RotatingFileHandler(
    LOG_FILE_CONTAINER_PATH, maxBytes=1024 * 1024, backupCount=3
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 2. The Console Logger (Prints to your Docker terminal)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 3. Attach both to the Root Logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler) # <-- This brings the terminal to life!

# --- Configuration from Environment Variables ---
GMX_USER = os.environ.get('GMX_USER')
GMX_PASS = os.environ.get('GMX_PASS')
IMAP_SERVER = 'imap.gmx.com'

SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASS = os.environ.get('SMTP_PASS')
REPLY_FROM_NAME = os.environ.get('REPLY_FROM_NAME', 'TechnoShed Services')

UPLOAD_DIR = os.environ.get('UPLOAD_DIR')
BASE_PUBLIC_URL = os.environ.get('BASE_PUBLIC_URL')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL_SECONDS', 300))
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')

# --- Helper Functions ---

def sanitize_path(path):
    """Strips illegal characters and prevents directory traversal."""
    if not path: return ""
    path = path.strip()
    path = re.sub(r'[\\|:*"<>?]', '', path)
    return path.replace('..', '').replace('/', os.sep).replace('\\', os.sep).strip(os.sep)

def generate_qr_code(url):
    """Generates a QR code image in memory."""
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
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

# --- The Universal Dispatcher ---

def send_universal_reply(recipient, status, subject_prefix, text_content, html_content, attachments=None):
    """Sends replies for ANY service."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"{subject_prefix}: {status}"
    msg['From'] = f"{REPLY_FROM_NAME} <{SMTP_USER}>" 
    msg['To'] = recipient

    msg.attach(MIMEText(text_content, 'plain'))
    msg.attach(MIMEText(html_content, 'html'))

    if attachments:
        for filename, file_bytes, maintype, subtype in attachments:
            attachment_part = MIMEBase(maintype, subtype)
            attachment_part.set_payload(file_bytes)
            email.encoders.encode_base64(attachment_part)
            attachment_part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(attachment_part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipient, msg.as_string()) 
        server.quit()
        logging.info(f"Universal reply sent successfully to {recipient}.")
    except Exception as e:
        logging.error(f"SMTP Error sending reply to {recipient}: {e}")

# --- Service Modules ---

def handle_file_upload(msg, sender, subject):
    """Original QR File Share Logic."""
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

def handle_translation(msg, sender, subject):
    """New GCP Document Translation Logic."""
    target_code = "ro"
    target_name = "Romanian"
    
    lang_map = {"polish": "pl", "lithuanian": "lt", "bulgarian": "bg", "spanish": "es"}
    if subject and subject.strip().lower() in lang_map:
        target_code = lang_map[subject.strip().lower()]
        target_name = subject.strip().title()

    client = translate.TranslationServiceClient()
    parent = f"projects/{GCP_PROJECT_ID}/locations/global"
    
    processed = 0
    for filename, raw_bytes in extract_valid_attachments(msg):
        if not filename.lower().endswith('.docx'):
            logging.warning(f"Skipping {filename}: Not a .docx file.")
            continue
            
        logging.info(f"Translating {filename} to {target_name}...")
        try:
            response = client.translate_document(
                request={
                    "parent": parent,
                    "target_language_code": target_code,
                    "source_language_code": "en",
                    "document_input_config": {
                        "content": raw_bytes,
                        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    },
                }
            )
            translated_bytes = response.document_translation.byte_stream_outputs[0]
            new_filename = filename.replace('.docx', f'_{target_code.upper()}.docx')
            
            html = f"<h2>✅ Translation Successful!</h2><p>Your document has been translated to {target_name} with formatting preserved.</p>"
            attachments = [(new_filename, translated_bytes, 'application', 'vnd.openxmlformats-officedocument.wordprocessingml.document')]
            
            send_universal_reply(sender, "SUCCESS", "Translation", "Document translated successfully.", html, attachments)
            processed += 1
        except Exception as e:
            logging.error(f"Translation failed: {e}")
            send_universal_reply(sender, "FAILED", "Translation", f"Error: {e}", f"<h2>❌ Translation Failed</h2><p>{e}</p>")

    if processed == 0:
        send_universal_reply(sender, "FAILED", "Translation", "No .docx files found.", "<h2>❌ Translation Failed</h2><p>Please attach a valid Word (.docx) file.</p>")

# --- The Router ---

def route_email_service(msg, sender, subject):
    """Traffic Cop: Routes email based on 'To' address."""
    raw_to = msg.get('To', '')
    recipient_address = email.utils.parseaddr(raw_to)[1].lower()
    logging.info(f"Routing request directed to: {recipient_address}")

    if "uploads@" in recipient_address:
        handle_file_upload(msg, sender, subject)
    elif "translations@" in recipient_address:
        handle_translation(msg, sender, subject)
    elif "vdat@" in recipient_address:
        logging.info("VDAT Module pending development.")
    else:
        send_universal_reply(sender, "FAILED", "Gateway Error", "Unknown Service.", f"<h2>❌ Unknown Service</h2><p>Address {recipient_address} is invalid.</p>")

# --- Core Loop ---

def process_email(msg, email_id, M):
    sender = email.utils.parseaddr(msg['from'])[1]
    subject = (msg.get('Subject') or "").strip()

    logging.info(f"\n--- Processing Email from {sender} ---")
    route_email_service(msg, sender, subject)
    
    M.store(email_id, '+FLAGS', '\\Seen')
    logging.info("---------------------------------") 
    return True

def check_mail():
    try:
        M = imaplib.IMAP4_SSL(IMAP_SERVER)
        M.login(GMX_USER, GMX_PASS)
        M.select('INBOX')
        status, email_ids = M.search(None, 'UNSEEN')
        id_list = email_ids[0].split()
        
        if id_list:
            logging.info(f"Found {len(id_list)} new emails.") 
            for email_id in id_list:
                status, msg_data = M.fetch(email_id, '(RFC822)')
                if status == 'OK':
                    msg = email.message_from_bytes(msg_data[0][1])
                    process_email(msg, email_id, M)
        M.logout()
    except Exception as e:
        logging.error(f"IMAP Error: {e}")

if __name__ == '__main__':
    logging.info("Starting TechnoShed Rincewind Universal Gateway...") 
    while True:
        check_mail()
        time.sleep(POLL_INTERVAL)