"""
Local web GUI for Coursera-Downloader.

Runs a small Flask server on localhost. The download itself runs in a
subprocess (start.py), so stopping a download is just killing the process
and the UI never freezes on logging output.

Usage:
    .venv/Scripts/python.exe webgui.py
Then open http://localhost:8765
"""

import os
import subprocess
import sys
import threading
from collections import deque

from flask import Flask, jsonify, render_template, request

import general
from localdb import SimpleDB

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(REPO_DIR, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

LOG_BUFFER_SIZE = 2000

app = Flask(__name__)
db = SimpleDB()

# Shared download state, guarded by lock
_state_lock = threading.Lock()
_state = {
    'process': None,        # subprocess.Popen of the running download
    'logs': deque(maxlen=LOG_BUFFER_SIZE),
    'log_offset': 0,        # total lines ever appended (for client polling)
    'running': False,
    'exit_code': None,
}


def _append_log(line):
    with _state_lock:
        _state['logs'].append(line.rstrip('\n'))
        _state['log_offset'] += 1


def _drain_pipe(pipe):
    """Read a subprocess pipe line by line and append to the log buffer."""
    try:
        for raw in iter(pipe.readline, ''):
            _append_log(raw.rstrip('\n'))
    except (ValueError, OSError):
        pass  # pipe closed when process is killed


def _run_download(cmd):
    with _state_lock:
        _state['running'] = True
        _state['exit_code'] = None
    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            creationflags=creationflags,
        )
        with _state_lock:
            _state['process'] = proc
        _append_log('[webgui] download started: %s' % ' '.join(cmd[1:]))
        _drain_pipe(proc.stdout)
        code = proc.wait()
        _append_log('[webgui] download finished (exit code %d)' % code)
        with _state_lock:
            _state['exit_code'] = code
    except Exception as exc:
        _append_log('[webgui] failed to start download: %s' % exc)
    finally:
        with _state_lock:
            _state['running'] = False
            _state['process'] = None


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/')
def index():
    argdict = db.read('argdict') or {}
    cauth_stored = bool((db.read('webgui') or {}).get('cauth'))
    return render_template(
        'index.html',
        languages=sorted(general.LANG_NAME_TO_CODE_MAPPING.keys()),
        argdict=argdict,
        cauth_stored=cauth_stored,
    )


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json(force=True)
    cauth = (data.get('cauth') or '').strip()
    course = (data.get('course') or '').strip()
    download_path = (data.get('path') or '').strip()

    # Reuse stored CAUTH when the field is left empty
    if not cauth:
        cauth = (db.read('webgui') or {}).get('cauth', '')
    if not cauth:
        return jsonify({'ok': False, 'error': 'CAUTH is required (paste it from DevTools)'}), 400

    classname = general.urltoclassname(course)
    if not classname:
        return jsonify({'ok': False, 'error': 'Invalid course slug or home page URL'}), 400
    if not download_path:
        return jsonify({'ok': False, 'error': 'Download folder is required'}), 400
    if not os.path.isdir(download_path):
        return jsonify({'ok': False, 'error': 'Download folder does not exist: %s' % download_path}), 400

    with _state_lock:
        if _state['running']:
            return jsonify({'ok': False, 'error': 'A download is already running'}), 409

    # Persist settings (CAUTH never leaves this machine)
    db.update('argdict.classname', course)
    db.update('argdict.path', download_path)
    db.update('argdict.video_resolution', data.get('resolution') or '720p')
    lang_name = data.get('language') or 'English'
    db.update('argdict.sl', lang_name)
    if 'webgui' in db._data:
        db.update('webgui.cauth', cauth)
    else:
        db.create('webgui', {'cauth': cauth})

    lang_code = general.LANG_NAME_TO_CODE_MAPPING.get(lang_name, 'en')

    cmd = [PYTHON, 'start.py', classname,
           '-ca', cauth,
           '--path', download_path,
           '--video-resolution', data.get('resolution') or '720p',
           '-sl', lang_code,
           '--download-quizzes',
           '--download-notebooks',
           '--jobs', '1']
    if data.get('resume'):
        cmd += ['--resume', '--cache-syllabus']

    with _state_lock:
        _state['logs'].clear()
        _state['log_offset'] = 0

    threading.Thread(target=_run_download, args=(cmd,), daemon=True).start()
    return jsonify({'ok': True, 'course': classname})


@app.route('/api/logs')
def api_logs():
    since = request.args.get('since', 0, type=int)
    with _state_lock:
        logs = list(_state['logs'])
        total = _state['log_offset']
        running = _state['running']
        exit_code = _state['exit_code']
    # `since` is the number of lines the client already has; the deque only
    # keeps the most recent LOG_BUFFER_SIZE lines, so convert the absolute
    # offset into an index into the buffered slice.
    skip = max(0, min(since - (total - len(logs)), len(logs)))
    return jsonify({
        'lines': logs[skip:],
        'total': total,
        'running': running,
        'exit_code': exit_code,
    })


@app.route('/api/stop', methods=['POST'])
def api_stop():
    with _state_lock:
        proc = _state['process']
    if proc is None or proc.poll() is not None:
        return jsonify({'ok': False, 'error': 'No download running'}), 409
    proc.terminate()
    _append_log('[webgui] stop requested, terminating download ...')
    return jsonify({'ok': True})


if __name__ == '__main__':
    print('Web GUI running at http://localhost:8765')
    app.run(host='127.0.0.1', port=8765, debug=False)