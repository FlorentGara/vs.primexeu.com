from io import BytesIO
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hetzner_url_dashboard as app


class FakeModel:
    def setInput(self, *_args):
        pass

    def forward(self):
        return np.full((1, 3, 256, 256), 128, dtype=np.float32)


class AuthenticatedHandler(app.Handler):
    def is_authenticated(self):
        return True

    def current_user(self):
        return {'username': 'batch-test'}

    def log_message(self, *_args):
        pass


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class RiegelBatchTests(unittest.TestCase):
    def test_batch_zip_contains_upload_folder_and_url(self):
        fixture = Path(__file__).parent / 'fixtures' / 'riegel-faint-15863.png'
        source_bytes = fixture.read_bytes()
        files = ThreadingHTTPServer(('127.0.0.1', 0), QuietFiles)
        api = ThreadingHTTPServer(('127.0.0.1', 0), AuthenticatedHandler)
        threads = [Thread(target=server.serve_forever, daemon=True) for server in (files, api)]
        for thread in threads:
            thread.start()
        job_id = None
        try:
            file_url = f'http://127.0.0.1:{files.server_address[1]}/tests/fixtures/riegel-faint-15863.png'
            api_url = f'http://127.0.0.1:{api.server_address[1]}'
            manifest = [
                {'source': 'upload', 'uploadIndex': 0},
                {'source': 'folder', 'path': str(fixture.resolve())},
                {'source': 'url', 'url': file_url},
            ]
            boundary = 'riegel-batch-test-boundary'
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="manifest"\r\n\r\n'
                f'{json.dumps(manifest)}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="upload_0"; filename="riegel-faint-15863.png"\r\n'
                f'Content-Type: image/png\r\n\r\n'
            ).encode() + source_bytes + f'\r\n--{boundary}--\r\n'.encode()
            request = Request(api_url + '/api/scan-riegel-logo/remove-all', data=body,
                              headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
            with patch('riegel_logo_remover._get_model', return_value=FakeModel()):
                with urlopen(request, timeout=30) as response:
                    started = json.load(response)
                job_id = started['job_id']
                for _ in range(100):
                    with urlopen(api_url + '/api/job?id=' + job_id, timeout=30) as response:
                        state = json.load(response)
                    if state['done']:
                        break
                    time.sleep(0.1)
            self.assertTrue(state['done'])
            self.assertTrue(state['ok'], state['message'])
            self.assertEqual(state['created'], 3)
            self.assertEqual(state['issues'], 0)
            with urlopen(api_url + '/api/scan-riegel-logo/remove-all/download?id=' + job_id, timeout=30) as response:
                self.assertEqual(response.status, 200)
                self.assertIn('Riegel_No_Logo.zip', response.headers['Content-Disposition'])
                archive_bytes = response.read()
            with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), 3)
                self.assertEqual(len(set(names)), 3)
                self.assertTrue(all(name.startswith('Riegel_No_Logo/') and name.endswith('.png') for name in names))
                self.assertTrue(all(archive.read(name).startswith(b'\x89PNG\r\n\x1a\n') for name in names))
            self.assertEqual(fixture.read_bytes(), source_bytes)
        finally:
            for server in (files, api):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)
            if job_id:
                job = app.JOBS.pop(job_id, {})
                output = job.get('output_path')
                if output:
                    Path(output).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()