import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import email.header # Added for robust filename decoding
import os
import time
import re
import smtplib
import qrcode
from io import BytesIO
import logging
from logging.handlers import RotatingFileHandler

from PIL import Image # Pillow/PIL is now available, but this import is good practice

# 🌟 NEW LOGGING CONFIGURATION 🌟

# 1. Define the log file path inside the container
LOG_FILE_CONTAINER_PATH = '/app/uploader.log'

# 2. Set up the file handler with rotation (max 1MB per file, keep 3 backup files)
file_handler = RotatingFileHandler(
    LOG_FILE_CONTAINER_PATH,
    maxBytes=1024 * 1024, # 1 Megabyte
    backupCount=3
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 3. Apply the configuration to the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)



# --- Configuration from Environment Variables ---
# IMAP for receiving
GMX_USER = os.environ.get('GMX_USER')
GMX_PASS = os.environ.get('GMX_PASS')
IMAP_SERVER = 'imap.gmx.com'

# SMTP for replying
SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASS = os.environ.get('SMTP_PASS')
REPLY_FROM_NAME = os.environ.get('REPLY_FROM_NAME')

# File paths and URL
UPLOAD_DIR = os.environ.get('UPLOAD_DIR')
BASE_PUBLIC_URL = os.environ.get('BASE_PUBLIC_URL')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL_SECONDS', 300))

# --- Helper Functions ---

def sanitize_path(path):
    """Strips illegal characters and prevents directory traversal (../)."""
    if not path:
        return ""
    # Remove dangerous characters and clean up separators
    path = path.strip()
    path = re.sub(r'[\\|:*"<>?]', '', path)
    path = path.replace('..', '')  # Prevent directory traversal
    path = path.replace('/', os.sep).replace('\\', os.sep)
    return path.strip(os.sep)

def generate_qr_code(url):
    """Generates a QR code image in memory (BytesIO) for the given URL."""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save image to a memory buffer
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        logging.error(f"Error generating QR code for {url}: {e}")
        return None

def send_reply(recipient, status, file_url=None, filename=None):
    """Sends a notification email back to the original sender."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"File Upload Status: {status}"
    
    # Use the authenticated SMTP_USER address in the header (required by GMX)
    msg['From'] = f"{REPLY_FROM_NAME} <{SMTP_USER}>" 
    msg['To'] = recipient

    # HTML Body Generation
    if status == "SUCCESS":
        text_content = f"Your file '{filename}' was successfully uploaded and is available at: {file_url}"
        html_content = f"""
        <html>
            <body>
                <h2>✅ Upload Successful!</h2>
                <p>Your file <strong>{filename}</strong> has been uploaded to the Techshed File Share.</p>
                <p>You can access or share the file using this secure link:</p>
                <p><a href="{file_url}">{file_url}</a></p>
                <p>The QR code for this link is attached to this email.</p>
                <br>
                <p>{REPLY_FROM_NAME} File Services</p>
            </body>
        </html>
        """
        qr_buffer = generate_qr_code(file_url)
        if qr_buffer:
            qr_img = MIMEImage(qr_buffer.read(), 'png')
            qr_img.add_header('Content-Disposition', 'attachment', filename='QR_Code.png')
            msg.attach(qr_img)
            
    else: # Failure or No Attachment
        text_content = "File upload failed or no valid attachment was found. Please ensure the email contains attachments and the subject is a valid path."
        html_content = f"""
        <html>
            <body>
                <h2>❌ Upload Failed</h2>
                <p>{text_content}</p>
                <p>Please check your subject line and ensure you have attached a file.</p>
            </body>
        </html>
        """

    msg.attach(MIMEText(text_content, 'plain'))
    msg.attach(MIMEText(html_content, 'html'))

    # Send the email via GMX SMTP
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        # Use SMTP_USER for sending, which is the ONLY address GMX allows.
        server.sendmail(SMTP_USER, recipient, msg.as_string()) 
        server.quit()
        logging.info(f"Reply sent successfully from {SMTP_USER} to {recipient}.")
    except Exception as e:
        logging.error(f"SMTP Error sending reply to {recipient}: {e}")


def process_email(msg, email_id, M):
    """Handles parsing, saving, and replying for a single email."""
    sender = email.utils.parseaddr(msg['from'])[1]
    
    # --- 1. Subject Line Handling (Fixes NoneType error) ---
    raw_subject = msg.get('Subject')
    if raw_subject is None:
        subject = "" # Default to empty string if subject is missing
    else:
        subject = raw_subject.strip()

    logging.info(f"\n--- Processing Email from {sender} ---")
    logging.info(f"Subject: {subject if subject else '[BLANK]'}") 
    
    relative_path = sanitize_path(subject)
    destination_folder = os.path.join(UPLOAD_DIR, relative_path)
    
    try:
        os.makedirs(destination_folder, exist_ok=True)
    except Exception as e:
        send_reply(sender, "FAILED", status=f"Error creating path: {relative_path}")
        return False

    attachments_processed = 0
    
    for part in msg.walk():
        # --- 2. Robust Attachment Filtering ---
        disposition = part.get_content_disposition()
        
        # We ONLY want files attached, not inline images (signatures)
        if disposition != 'attachment':
            continue
            
        raw_filename = part.get_filename()
        if raw_filename:
            # Decode the filename header to handle special characters
            filename, encoding = email.header.decode_header(raw_filename)[0]
            
            if isinstance(filename, bytes):
                try:
                    # Safely decode the filename
                    filename = filename.decode(encoding or 'utf-8', errors='ignore')
                except:
                    logging.warning(f"Failed to decode filename: {raw_filename}. Using raw string.")
                    filename = raw_filename
            
            # --- 3. Save the File ---
            safe_filename = sanitize_path(filename) 
            
            if not safe_filename:
                 logging.warning("Skipping attachment with unresolvable filename.")
                 continue

            filepath = os.path.join(destination_folder, safe_filename)
            
            try:
                with open(filepath, 'wb') as fp:
                    fp.write(part.get_payload(decode=True))
            except Exception as e:
                logging.error(f"Failed to write file {safe_filename} to disk: {e}")
                continue
                
            # Construct the final public URL
            final_url = f"{BASE_PUBLIC_URL}/{relative_path.replace(os.sep, '/')}/{safe_filename}"
            
            logging.info(f"SUCCESS: Saved {safe_filename} to {filepath}") 
            attachments_processed += 1
            
            # Send reply immediately for this file
            send_reply(sender, "SUCCESS", file_url=final_url, filename=safe_filename)
            
    if attachments_processed == 0:
        send_reply(sender, "FAILED", status="No valid attachment found, or files were filtered (e.g., inline images).")
        
    M.store(email_id, '+FLAGS', '\\Seen')
    
    logging.info("---------------------------------") 
    return attachments_processed > 0

def check_mail():
    """Connects to GMX and polls for unread mail."""
    # ... (IMAP connection and polling logic remains the same)
    try:
        M = imaplib.IMAP4_SSL(IMAP_SERVER)
        M.login(GMX_USER, GMX_PASS)
        logging.info("Successfully logged into GMX.") 
        
        M.select('INBOX')
        status, email_ids = M.search(None, 'UNSEEN')
        id_list = email_ids[0].split()
        
        if not id_list:
            logging.info(f"No new emails found. Sleeping for {POLL_INTERVAL}s.") 
            return

        logging.info(f"Found {len(id_list)} new emails to process.") 
        
        for email_id in id_list:
            status, msg_data = M.fetch(email_id, '(RFC822)')
            if status == 'OK':
                msg = email.message_from_bytes(msg_data[0][1])
                process_email(msg, email_id, M)
            else:
                 logging.error(f"Error fetching email {email_id}")
            
        M.logout()
        
    except imaplib.IMAP4.error as e:
        logging.error(f"IMAP Login/Connection Error: {e}") 
        logging.error("Please check GMX user/password or if IMAP is enabled.") 
    except Exception as e:
        logging.error(f"An unexpected error occurred in check_mail: {e}")

if __name__ == '__main__':
    if not all([GMX_USER, GMX_PASS, SMTP_SERVER, SMTP_PASS, UPLOAD_DIR, BASE_PUBLIC_URL]):
        logging.critical("CRITICAL: Missing one or more required environment variables.") 
        logging.critical("Please ensure GMX/SMTP credentials, UPLOAD_DIR, and BASE_PUBLIC_URL are set.") 
        exit(1)
        
    logging.info(f"Starting Techshed Email Uploader. Target URL: {BASE_PUBLIC_URL}") 
    
    while True:
        check_mail()
        time.sleep(POLL_INTERVAL)
        