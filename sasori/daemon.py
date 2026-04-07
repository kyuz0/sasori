import imaplib
import smtplib
import sqlite3
import time
import os
import sys
import signal
import json
import email
from email.message import EmailMessage
import subprocess
import threading
from pathlib import Path
from email.header import decode_header
import re
import importlib.util

CONFIG_DIR = Path.cwd()
HANDLERS_DIR = CONFIG_DIR / "handlers"
DB_PATH = CONFIG_DIR / "sasori.db"

# Env vars
IMAP_SERVER = os.environ.get("IMAP_SERVER", "imap.gmail.com")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
EMAIL_ACCOUNT = os.environ.get("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
WHITELIST_EMAILS = [e.strip().lower() for e in os.environ.get("WHITELIST_EMAILS", "").split(",") if e.strip()]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 15))
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", 1))

_handlers = {}

def init_env():
    HANDLERS_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS threads 
                        (thread_id TEXT PRIMARY KEY, subject TEXT, status TEXT, 
                         start_time REAL, current_pid INTEGER, handler_tag TEXT, user_email TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS messages 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT, content TEXT)''')
        conn.commit()

def load_handlers():
    global _handlers
    _handlers.clear()
    for py_file in HANDLERS_DIR.glob("*.py"):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
                if hasattr(module, "HANDLERS"):
                    for h in module.HANDLERS:
                        _handlers[h.agent_tag.lower()] = h
            except Exception as e:
                log(f"Error loading handler {py_file}: {e}")
    log(f"Loaded handlers for: {list(_handlers.keys())}")

def log(msg):
    print(f"[Sasori] {msg}", flush=True)

def send_email(to_email, subject, body, in_reply_to=None, attachments=None):
    if not EMAIL_ACCOUNT or not EMAIL_PASSWORD:
        return
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_ACCOUNT
    msg['To'] = to_email
    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
        msg['References'] = in_reply_to
        
    for att in (attachments or []):
        try:
            with open(att, 'rb') as f:
                msg.add_attachment(f.read(), maintype='application', subtype='octet-stream', filename=os.path.basename(att))
        except Exception as e:
            log(f"Failed to attach {att}: {e}")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as server:
            server.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        log(f"SMTP Error: {e}")

def decode_mime_words(s):
    if not s: return ""
    return u''.join(word.decode(encoding or 'utf-8') if isinstance(word, bytes) else word for word, encoding in decode_header(s))

def extract_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain': return part.get_payload(decode=True).decode('utf-8', errors='ignore')
    else: return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return ""

def clean_email_body(body):
    lines = [L for L in body.splitlines() if not (L.startswith(">") or (L.startswith("On ") and "wrote:" in L))]
    return "\n".join(lines).strip()

def run_agent_task(thread_id, user_email, subject, handler_tag):
    handler = _handlers.get(handler_tag)
    if not handler: return
    
    with sqlite3.connect(DB_PATH) as conn:
        messages = conn.execute("SELECT role, content FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,)).fetchall()
    
    history = [{"role": r, "content": c} for r, c in messages]
    tmp_file = f"/tmp/thread_{thread_id}.json"
    out_file = f"/tmp/thread_{thread_id}.out"
    with open(tmp_file, "w") as f: json.dump(history, f)
        
    log(f"Dispatching to {handler_tag} for {thread_id}")
    try:
        proc = handler.execute(thread_id, tmp_file, out_file)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE threads SET status = 'RUNNING', start_time = ?, current_pid = ? WHERE thread_id = ?", (time.time(), proc.pid, thread_id))
            conn.commit()
            
        send_email(user_email, subject, f"Sasori: Agent {handler_tag} has started running.")
        
        proc.wait()
        
        with sqlite3.connect(DB_PATH) as conn:
            status = conn.execute("SELECT status FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
            if status[0] == 'STOPPED':
                res_text = "[Agent was manually stopped.]"
                attachments = []
            else:
                conn.execute("UPDATE threads SET status = 'DONE', current_pid = NULL WHERE thread_id = ?", (thread_id,))
                conn.commit()
                res_text, attachments = handler.process_result(thread_id, out_file, history[-1]["content"])
                
                # Clean ansi
                ansi_esc = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                res_text = "\n".join([ansi_esc.sub('', L) for L in res_text.splitlines()])
                
                conn.execute("INSERT INTO messages (thread_id, role, content) VALUES (?, 'assistant', ?)", (thread_id, res_text))
                conn.commit()
                
            send_email(user_email, subject, res_text, attachments=attachments)
    except Exception as e:
        log(f"Agent crash {thread_id}: {e}")
        send_email(user_email, subject, f"System Failure: {e}")
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE threads SET status = 'DONE' WHERE thread_id = ?", (thread_id,))
            conn.commit()

def drain_queue():
    with sqlite3.connect(DB_PATH) as conn:
        running = conn.execute("SELECT COUNT(*) FROM threads WHERE status = 'RUNNING'").fetchone()[0]
        if running >= MAX_CONCURRENT_AGENTS: return
        
        available = MAX_CONCURRENT_AGENTS - running
        queued = conn.execute("SELECT thread_id, user_email, subject, handler_tag FROM threads WHERE status = 'QUEUED' ORDER BY start_time ASC LIMIT ?", (available,)).fetchall()
        for row in queued:
            worker = threading.Thread(target=run_agent_task, args=(row[0], row[1], row[2], row[3]))
            worker.daemon = True
            worker.start()

def process_mailbox():
    if not EMAIL_ACCOUNT or not EMAIL_PASSWORD: return
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        status, email_ids = mail.search(None, 'UNSEEN')
        if status != 'OK': return
        
        eids = email_ids[0].split()
        if eids: log(f"Found {len(eids)} UNSEEN emails being processed...")
        
        for eid in eids:
            status, data = mail.fetch(eid, '(RFC822)')
            if status != 'OK': continue
            msg = email.message_from_bytes(data[0][1])
            
            from_head = decode_mime_words(msg.get("From", ""))
            subject = decode_mime_words(msg.get("Subject", ""))
            from_email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_head)
            if not from_email_match: continue
            from_email = from_email_match.group(0).lower()
            
            if WHITELIST_EMAILS and from_email not in WHITELIST_EMAILS:
                log(f"Dropped email from {from_email}: not in WHITELIST_EMAILS.")
                continue
            
            body = clean_email_body(extract_body(msg)).strip()
            
            # Global STATUS check
            is_global_status = (body.upper() == "STATUS" or subject.upper().strip() == "STATUS")
            if not re.search(r'\[Thread-[a-zA-Z0-9]+\]', subject) and is_global_status:
                with sqlite3.connect(DB_PATH) as conn:
                    running = conn.execute("SELECT thread_id, subject, start_time FROM threads WHERE status = 'RUNNING'").fetchall()
                if not running: send_email(from_email, subject, "Sasori: 0 Active Threads.")
                else:
                    lines = [f"Sasori Active Threads ({len(running)}/{MAX_CONCURRENT_AGENTS}):"]
                    for t_id, subj, st in running: lines.append(f"- [{t_id}] {subj} ({int(time.time()-st)}s elapsed)")
                    send_email(from_email, subject, "\n".join(lines))
                continue

            # Handler Matching
            # Match if subject starts with tag (e.g. "[test-agent]") or tag without brackets (e.g. "test-agent")
            matched_tag = next((tag for tag in _handlers.keys() if subject.lower().startswith(tag) or subject.lower().lstrip("[").startswith(tag.strip("[]"))), None)
            if not matched_tag and not re.search(r'\[Thread-[a-zA-Z0-9]+\]', subject):
                log(f"Dropped email '{subject}': did not match any agent tags or global commands.")
                continue # Ignore

            with sqlite3.connect(DB_PATH) as conn:
                thread_match = re.search(r'\[Thread-([a-zA-Z0-9]+)\]', subject)
                if thread_match:
                    thread_id = thread_match.group(1)
                    row = conn.execute("SELECT status, current_pid, start_time FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
                    if row:
                        t_stat, c_pid, st = row
                        if body.upper() == "STOP" and t_stat in ["RUNNING", "QUEUED"]:
                            if c_pid: os.kill(c_pid, signal.SIGTERM)
                            conn.execute("UPDATE threads SET status = 'STOPPED' WHERE thread_id = ?", (thread_id,))
                            conn.commit()
                            send_email(from_email, subject, f"Thread {thread_id} stopped.")
                            continue
                        elif body.upper() == "STATUS" or subject.upper().startswith("STATUS"):
                            if t_stat == "QUEUED":
                                send_email(from_email, subject, f"Thread {thread_id} is QUEUED.")
                            elif t_stat == "RUNNING":
                                elapsed = int(time.time() - st)
                                tail = "Unable to read output."
                                try:
                                    with open(f"/tmp/thread_{thread_id}.out", "r") as f:
                                        tail = "".join(f.readlines()[-30:])
                                except: pass
                                send_email(from_email, subject, f"Thread {thread_id} RUNNING ({elapsed}s).\n\nTail:\n{tail}")
                            else: send_email(from_email, subject, f"Thread {thread_id} is {t_stat}.")
                            continue
                        elif t_stat in ["RUNNING", "QUEUED"]:
                            send_email(from_email, subject, "Thread is busy. Reply STOP to cancel before submitting another prompt.")
                            continue
                else: 
                    thread_id = os.urandom(4).hex()
                    subject = f"{subject} [Thread-{thread_id}]"

                if not matched_tag:
                    row = conn.execute("SELECT handler_tag FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
                    if row: matched_tag = row[0]
                    else: continue

                conn.execute("INSERT OR IGNORE INTO threads (thread_id, subject, status, start_time, handler_tag, user_email) VALUES (?, ?, 'QUEUED', ?, ?, ?)", (thread_id, subject, time.time(), matched_tag, from_email))
                conn.execute("UPDATE threads SET status = 'QUEUED', start_time = ? WHERE thread_id = ?", (time.time(), thread_id))
                conn.execute("INSERT INTO messages (thread_id, role, content) VALUES (?, 'user', ?)", (thread_id, body))
                
                running_cnt = conn.execute("SELECT COUNT(*) FROM threads WHERE status = 'RUNNING'").fetchone()[0]
                if running_cnt >= MAX_CONCURRENT_AGENTS:
                    q_cnt = conn.execute("SELECT COUNT(*) FROM threads WHERE status = 'QUEUED'").fetchone()[0]
                    send_email(from_email, subject, f"Sasori: Task {matched_tag} enqueued. (Position: {q_cnt})")
                    
                conn.commit()
    except Exception as e:
        log(f"IMAP Trap: {e}")

def main():
    if not (EMAIL_ACCOUNT and EMAIL_PASSWORD):
        log("ERROR: MISSING CREDENTIALS")
        sys.exit(1)
    init_env()
    load_handlers()
    log(f"Sasori polling (Int:{POLL_INTERVAL}s, MaxConcurrent:{MAX_CONCURRENT_AGENTS})")
    while True:
        try: process_mailbox()
        except Exception as e: log(f"Poll loop crash: {e}")
        drain_queue()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__": main()
