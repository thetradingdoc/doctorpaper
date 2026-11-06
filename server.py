"""DoctorPaper local hackathon API: review-first medical document dashboard.

NOT a hosted medical data service or HIPAA-compliant deployment. Bind loopback
by default, use synthetic data for demonstrations. Documents are never sent to
external OCR services; installed tesseract/pdftotext run locally.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
DATA = Path(os.getenv('DOCTORPAPER_DATA_DIR', str(ROOT / '.local-data')))
DB = DATA / 'doctorpaper.db'
PORT = int(os.getenv('PORT', '8787'))
HOST = os.getenv('HOST', '127.0.0.1')
TOKEN = os.getenv('DOCTORPAPER_API_TOKEN') or secrets.token_urlsafe(24)
MAX_BYTES = 10 * 1024 * 1024
KINDS = {'Bill', 'Record', 'EOB', 'Receipt', 'Skin photo', 'Rx'}
STAGES = ['request_received', 'context_ready', 'calling_provider', 'checking_availability', 'confirming_details', 'booked']
_lock = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def initialize():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL,
          kind TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
          raw_text TEXT NOT NULL, fields TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS appointments (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          document_ids TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
          provider TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
          notes TEXT NOT NULL, events TEXT NOT NULL
        );
        ''')


def extract_fields(text):
    """Conservative heuristic extraction. All results are unverified until review."""
    text = text[:120000]
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    def find(pattern):
        m = re.search(pattern, text, re.I | re.M)
        return m.group(1).strip(' .:-') if m else ''
    fields = {
        'patient_name': find(r'^\s*(?:patient(?: name)?|member(?: name)?|insured)\s*[:#-]\s*([^\n]{2,80})'),
        'provider': find(r'^\s*(?:provider|facility|clinic|hospital|billed by)\s*[:#-]\s*([^\n]{2,100})'),
        'insurance': find(r'^\s*(?:insurance|payer|plan|health plan)\s*[:#-]\s*([^\n]{2,100})'),
        'member_id': find(r'^\s*(?:member id|subscriber id|policy number)\s*[:#-]\s*([A-Za-z0-9-]{3,40})'),
        'date': find(r'^\s*(?:date of service|service date|visit date|appointment date|date)\s*[:#-]\s*([A-Za-z0-9, /-]{6,36})'),
        'amount': find(r'^\s*(?:amount due|balance due|total due|patient responsibility|total)\s*[:$#-]*\s*(\$?\s?[\d,]+(?:\.\d{2})?)'),
    }
    return {k: v[:120] for k,v in fields.items()}


def ocr_bytes(content, media_type):
    if media_type == 'application/pdf':
        suffix, cmd = '.pdf', ['pdftotext', '-layout', '-']
    else:
        suffix, cmd = '.png', ['tesseract', 'stdin', 'stdout']
    try:
        p = subprocess.run(cmd, input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=18)
        if p.returncode == 0:
            return p.stdout.decode('utf-8', errors='replace')[:120000], ''
        return '', 'Local text extraction could not read this file. Review details manually.'
    except (OSError, subprocess.TimeoutExpired):
        return '', 'Local OCR is unavailable. Install Tesseract (images) or pdftotext (PDFs), or enter details manually.'


def document(row):
    d = dict(row)
    d['fields'] = json.loads(d['fields'])
    d['reviewed'] = bool(d['reviewed'])
    d.pop('raw_text', None)
    return d


def appointment(row):
    d = dict(row)
    d['document_ids'] = json.loads(d['document_ids'])
    d['events'] = json.loads(d['events'])
    return d


def read_documents():
    with db() as con:
        return [document(x) for x in con.execute('SELECT * FROM documents ORDER BY created_at DESC')]


def read_appointments():
    with db() as con:
        return [appointment(x) for x in con.execute('SELECT * FROM appointments ORDER BY created_at DESC')]


class Handler(BaseHTTPRequestHandler):
    server_version = 'DoctorPaperLocal/1.0'
    def log_message(self, format, *args):
        # Don't log paths or sensitive request contents.
        sys.stderr.write('DoctorPaper: HTTP request handled\n')

    def response_headers(self, code, content_type, length):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()

    def reply(self, obj, code=200):
        payload = json.dumps(obj, ensure_ascii=False).encode()
        self.response_headers(code, 'application/json; charset=utf-8', len(payload))
        self.wfile.write(payload)

    def fail(self, reason, code=400):
        self.reply({'error': reason}, code)

    def authorized(self):
        h = self.headers.get('Authorization', '')
        return h.startswith('Bearer ') and hmac.compare_digest(h[7:], TOKEN)

    def json_body(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_BYTES * 2:
                raise ValueError('Request size not allowed')
            obj = json.loads(self.rfile.read(size))
            if not isinstance(obj, dict):
                raise ValueError('Expected object')
            return obj
        except (ValueError, json.JSONDecodeError, UnicodeError):
            raise ValueError('Invalid JSON payload')

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ('/', '/index.html'):
            path, typ = STATIC / 'index.html', 'text/html; charset=utf-8'
        elif url.path in ('/app.css', '/app.js'):
            path = STATIC / url.path[1:]
            typ = 'text/css; charset=utf-8' if url.path.endswith('.css') else 'text/javascript; charset=utf-8'
        elif url.path == '/api/health':
            return self.reply({'ok': True, 'version': 1})
        elif url.path.startswith('/api/'):
            if not self.authorized():
                return self.fail('Unauthorized', 401)
            if url.path == '/api/documents':
                return self.reply({'documents': read_documents()})
            if url.path == '/api/appointments':
                return self.reply({'appointments': read_appointments()})
            if url.path == '/api/agent/context':
                # Review requirement: exclude any unreviewed extraction.
                docs = [d for d in read_documents() if d['reviewed']]
                return self.reply({'schema': 'doctorpaper.agent-context.v1', 'documents': [
                    {'id': d['id'], 'kind': d['kind'], 'fields': d['fields']} for d in docs
                ], 'notice': 'User-reviewed data only. Verify details with patient before booking.'})
            if url.path.startswith('/api/appointments/'):
                apid = url.path.split('/')[-1]
                with db() as con:
                    row = con.execute('SELECT * FROM appointments WHERE id=?', (apid,)).fetchone()
                return self.reply({'appointment': appointment(row)}) if row else self.fail('Not found', 404)
            return self.fail('Not found', 404)
        else:
            return self.fail('Not found', 404)
        data = path.read_bytes()
        self.response_headers(200, typ, len(data))
        self.wfile.write(data)

    def do_POST(self):
        if not self.path.startswith('/api/'):
            return self.fail('Not found', 404)
        if not self.authorized():
            return self.fail('Unauthorized', 401)
        try:
            obj = self.json_body()
            if self.path == '/api/documents':
                name = str(obj.get('filename', 'document'))[:160]
                typ = str(obj.get('media_type', ''))
                kind = str(obj.get('kind', 'Record'))
                if kind not in KINDS or typ not in {'image/png', 'image/jpeg', 'image/webp', 'application/pdf'}:
                    return self.fail('Unsupported document type', 415)
                raw = obj.get('content_base64', '')
                content = base64.b64decode(raw, validate=True)
                if not content or len(content) > MAX_BYTES:
                    return self.fail('Document must be 1 byte to 10 MB', 413)
                if typ == 'application/pdf' and not content.startswith(b'%PDF'):
                    return self.fail('Invalid PDF', 415)
                if typ == 'image/png' and not content.startswith(b'\x89PNG'):
                    return self.fail('Invalid PNG', 415)
                if typ == 'image/jpeg' and not content.startswith(b'\xff\xd8'):
                    return self.fail('Invalid JPEG', 415)
                if typ == 'image/webp' and content[:4] != b'RIFF':
                    return self.fail('Invalid WebP', 415)
                txt, warning = ocr_bytes(content, typ)
                did = uuid4().hex
                # Store metadata and extracted text only. Original binary stays in user browser.
                with _lock, db() as con:
                    con.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,0)',
                         (did,name,typ,kind,len(content),now(),txt,json.dumps(extract_fields(txt))))
                    row = con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
                return self.reply({'document': document(row), 'warning': warning}, 201)
            if self.path.startswith('/api/documents/') and self.path.endswith('/review'):
                did = self.path.split('/')[-2]
                fields = obj.get('fields')
                if not isinstance(fields, dict):
                    return self.fail('Expected fields object')
                keys = {'patient_name','provider','insurance','member_id','date','amount'}
                if set(fields) != keys or any(not isinstance(v, str) or len(v) > 120 for v in fields.values()):
                    return self.fail('Invalid review fields')
                with _lock, db() as con:
                    count = con.execute('UPDATE documents SET fields=?, reviewed=1 WHERE id=?', (json.dumps(fields),did)).rowcount
                    row = con.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
                return self.reply({'document':document(row)}) if count else self.fail('Not found',404)
            if self.path == '/api/appointments':
                ids = obj.get('document_ids',[])
                if not isinstance(ids,list) or not ids or len(ids)>20 or not all(isinstance(x,str) for x in ids):
                    return self.fail('Select at least one reviewed document')
                with _lock, db() as con:
                    rows = list(con.execute('SELECT id FROM documents WHERE reviewed=1 AND id IN (%s)' % ','.join('?' for _ in ids), ids))
                    if len({r['id'] for r in rows}) != len(set(ids)):
                        return self.fail('All selected documents must be reviewed')
                    aid = uuid4().hex
                    event = {'stage':'request_received','detail':'Request created; waiting for voice-agent handoff','at':now()}
                    con.execute('INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (aid,now(),now(),json.dumps(list(dict.fromkeys(ids))),'request_received','pending','','','','',json.dumps([event])))
                return self.reply({'appointment_id':aid,'stage':'request_received'},201)
            if self.path.startswith('/api/appointments/') and self.path.endswith('/events'):
                aid = self.path.split('/')[-2]
                stage = str(obj.get('stage',''))
                detail = str(obj.get('detail',''))[:220]
                if stage not in STAGES + ['failed','cancelled']:
                    return self.fail('Invalid stage')
                values = {k:str(obj.get(k,''))[:120] for k in ['provider','date','time','notes']}
                with _lock, db() as con:
                    row = con.execute('SELECT * FROM appointments WHERE id=?', (aid,)).fetchone()
                    if not row: return self.fail('Not found',404)
                    existing = appointment(row)
                    if existing['status'] in {'booked','failed','cancelled'}:
                        return self.fail('Appointment already closed',409)
                    if stage in STAGES and STAGES.index(stage) < STAGES.index(existing['stage']):
                        return self.fail('Cannot move stage backwards',409)
                    if stage == 'booked' and (not values['provider'] or not values['date'] or not values['time']):
                        return self.fail('Confirmed booking requires provider, date, time',400)
                    status = 'booked' if stage == 'booked' else stage if stage in ('failed','cancelled') else 'in_progress'
                    events = existing['events'] + [{'stage':stage,'detail':detail or stage.replace('_',' ').title(),'at':now()}]
                    merged = {k:values[k] or existing[k] for k in values}
                    con.execute('UPDATE appointments SET updated_at=?,stage=?,status=?,provider=?,date=?,time=?,notes=?,events=? WHERE id=?',
                        (now(),stage,status,merged['provider'],merged['date'],merged['time'],merged['notes'],json.dumps(events),aid))
                return self.reply({'appointment_id':aid,'stage':stage,'status':status})
            return self.fail('Not found',404)
        except (ValueError, base64.binascii.Error) as exc:
            return self.fail(str(exc),400)
        except Exception:
            return self.fail('Internal error',500)


if __name__ == '__main__':
    initialize()
    if HOST not in ('127.0.0.1','localhost','::1'):
        print('WARNING: Non-loopback deployment requires HTTPS, identity, security review and compliant infrastructure.',file=sys.stderr)
    print(f'DoctorPaper: http://{HOST}:{PORT}\nLocal API token: {TOKEN}\nDo not use real patient records in an insecure demo.',flush=True)
    ThreadingHTTPServer((HOST,PORT), Handler).serve_forever()
