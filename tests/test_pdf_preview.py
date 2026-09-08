from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import sys

import pytest

from leopard_project.web import pdf_preview
from leopard_project.web.repository import ReportRepository
from test_web_mvp import web, login, minimal_renderable_pdf  # noqa: F401


@pytest.fixture()
def preview(web):
    client, sessions, settings = web
    login(client)
    content = minimal_renderable_pdf()
    response = client.post('/api/v1/admin/reports', files={'file': ('small.pdf', content, 'application/pdf')})
    assert response.status_code == 201
    report_id = response.json()['report']['id']
    with sessions() as session:
        stored = ReportRepository(session).by_id(report_id).file.storage_filename
    return client, f'/api/v1/reports/{report_id}/pdf', settings.upload_dir / stored, content


@pytest.mark.parametrize('failure', ['sigtrap', 'exit', 'timeout'])
@pytest.mark.parametrize('suffix', ['/preview', '/preview/pages/1'])
def test_worker_failure_does_not_kill_api(preview, monkeypatch, failure, suffix):
    client, url, _, original = preview
    pid = os.getpid()
    scripts = {
        'sigtrap': 'import os,signal,resource; resource.setrlimit(resource.RLIMIT_CORE,(0,0)); os.kill(os.getpid(),signal.SIGTRAP)',
        'exit': 'raise SystemExit(7)',
        'timeout': 'import time; time.sleep(20)',
    }
    with monkeypatch.context() as patch:
        patch.setattr(pdf_preview, '_worker_command', lambda *_: [sys.executable, '-c', scripts[failure]])
        if failure == 'timeout':
            patch.setattr(pdf_preview, '_WORKER_TIMEOUT_SECONDS', .1)
        response = client.get(url + suffix)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'pdf_preview_unavailable'
    assert 'PDF预览暂不可用' in response.json()['error']['message']
    assert client.get('/api/v1/docs').status_code == 200 and os.getpid() == pid
    opened = client.get(url + '/open')
    assert opened.status_code == 200 and opened.content == original
    assert opened.headers['content-disposition'].startswith('inline;')
    downloaded = client.get(url + '/download')
    assert downloaded.content == original
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    # Failure releases the capacity and a later valid request still works.
    assert client.get(url + '/preview/pages/1').status_code == 200


def test_invalid_pdf_and_invalid_pages_are_graceful(preview):
    client, url, path, _ = preview
    for page in (0, -1, 2, 99999):
        response = client.get(url + f'/preview/pages/{page}')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'pdf_page_not_found'
    path.write_bytes(b'%PDF-1.4\ncorrupted fixture')
    for suffix in ('/preview', '/preview/pages/1'):
        response = client.get(url + suffix)
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'pdf_preview_unavailable'
    assert client.get('/api/v1/docs').status_code == 200
    assert client.get(url + '/download').content == path.read_bytes()


def test_repeated_and_browser_concurrent_preview_requests(preview):
    client, url, _, _ = preview
    pid = os.getpid()
    expected = client.get(url + '/preview/pages/1').content
    assert expected.startswith(b'\x89PNG')
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.get(url + '/preview/pages/1'), range(12)))
    assert all(r.status_code == 200 and r.content == expected for r in responses)
    assert os.getpid() == pid and client.get('/api/v1/docs').status_code == 200


def test_busy_preview_capacity_fails_closed_without_starting_worker(preview, monkeypatch):
    client, url, _, _ = preview
    assert pdf_preview._SLOTS.acquire(blocking=False)
    assert pdf_preview._SLOTS.acquire(blocking=False)
    try:
        monkeypatch.setattr(pdf_preview, '_QUEUE_TIMEOUT_SECONDS', .01)
        response = client.get(url + '/preview')
        assert response.status_code == 503
    finally:
        pdf_preview._SLOTS.release()
        pdf_preview._SLOTS.release()
    assert client.get(url + '/preview').status_code == 200
