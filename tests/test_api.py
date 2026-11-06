"""Synthetic end-to-end local API contract checks."""
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from http.server import ThreadingHTTPServer

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        server.DATA=Path(cls.tmp.name)
        server.DB=server.DATA/'testing.db'
        server.TOKEN='unit-test-token'
        server.initialize()
        cls.host=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.host.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.host.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.host.shutdown();cls.host.server_close();cls.thread.join(timeout=3);cls.tmp.cleanup()
    def api(self,path,body=None,token='unit-test-token'):
        headers={'Authorization':'Bearer '+token}
        data=None
        if body is not None:
            data=json.dumps(body).encode();headers['Content-Type']='application/json'
        req=urllib.request.Request(self.base+"/api"+path,data=data,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=4) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def test_static_dashboard_and_assets(self):
        for path, marker, mime in (
            ('/', b'DoctorPaper', 'text/html'),
            ('/index.html', b'DoctorPaper', 'text/html'),
            ('/app.css', b'.shell', 'text/css'),
            ('/app.js', b'STAGES', 'text/javascript'),
        ):
            with self.subTest(path=path):
                with urllib.request.urlopen(self.base + path, timeout=4) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(mime, response.headers['Content-Type'])
                    self.assertIn(marker, response.read())

    def test_review_gate_and_events(self):
        status,_=self.api('/documents',token='wrong')
        self.assertEqual(status,401)
        status,up=self.api('/documents',{'filename':'synthetic.png','media_type':'image/png','kind':'Bill','content_base64':base64.b64encode(b'\x89PNG\r\n\x1a\nsynthetic-test').decode()})
        self.assertEqual(status,201)
        did=up['document']['id']
        self.assertFalse(up['document']['reviewed'])
        self.assertEqual(self.api('/appointments',{'document_ids':[did]})[0],400)
        self.assertEqual(self.api('/agent/context')[1]['documents'],[])
        fields={k:'' for k in ('patient_name','provider','insurance','member_id','date','amount')}
        fields.update(patient_name='TEST PATIENT',insurance='SYNTHETIC PLAN')
        self.assertEqual(self.api('/documents/'+did+'/review',{'fields':fields})[0],200)
        self.assertEqual(self.api('/agent/context')[1]['documents'][0]['fields']['insurance'],'SYNTHETIC PLAN')
        status,ap=self.api('/appointments',{'document_ids':[did]})
        self.assertEqual(status,201)
        aid=ap['appointment_id']
        self.assertEqual(self.api('/appointments/'+aid+'/events',{'stage':'booked'})[0],400)
        self.assertEqual(self.api('/appointments/'+aid+'/events',{'stage':'context_ready','detail':'Ready'})[0],200)
        self.assertEqual(self.api('/appointments/'+aid+'/events',{'stage':'request_received'})[0],409)
        self.assertEqual(self.api('/appointments/'+aid+'/events',{'stage':'booked','provider':'Test clinic','date':'2026-11-12','time':'10:30'})[0],200)
        detail=self.api('/appointments/'+aid)[1]['appointment']
        self.assertEqual(detail['status'],'booked')
        self.assertEqual(len(detail['events']),3)
        self.assertEqual(self.api('/appointments/'+aid+'/events',{'stage':'booked','provider':'Test clinic','date':'2026-11-12','time':'10:30'})[0],409)
    def test_extraction(self):
        fields=server.extract_fields('Patient Name: Sample Person\nProvider: Sample Hospital\nInsurance: Example PPO\nMember ID: D-123\nDate of Service: 11/06/2026\nAmount Due: $45.20')
        self.assertEqual(fields['patient_name'],'Sample Person')
        self.assertEqual(fields['amount'],'$45.20')
        self.assertEqual(fields['insurance'],'Example PPO')

if __name__=='__main__':unittest.main()
