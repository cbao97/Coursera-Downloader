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
import time
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
# SimpleDB is written from multiple threads (record result, persist settings)
_db_lock = threading.Lock()
_state = {
    'process': None,        # subprocess.Popen of the running download
    'logs': deque(maxlen=LOG_BUFFER_SIZE),
    'log_offset': 0,        # total lines ever appended (for client polling)
    'running': False,
    'exit_code': None,
    'failed_urls': [],      # URLs tagged [FAILED_URL] by coursera_dl
    'stats': {'downloaded': 0, 'skipped': 0},
    'started_at': None,
    'finished_at': None,
}


def _append_log(line):
    stripped = line.rstrip('\n')
    with _state_lock:
        _state['logs'].append(stripped)
        _state['log_offset'] += 1
        if '[FAILED_URL] ' in stripped:
            url = stripped.split('[FAILED_URL] Downloading: ' if '[FAILED_URL] Downloading: ' in stripped else '[FAILED_URL] ', 1)[1].strip()
            if url and url not in _state['failed_urls']:
                _state['failed_urls'].append(url)
        # Count download activity for the end-of-run summary
        if stripped.startswith('Downloading: '):
            _state['stats']['downloaded'] += 1
        elif ' already downloaded' in stripped:
            _state['stats']['skipped'] += 1


def _drain_pipe(pipe):
    """Read a subprocess pipe line by line and append to the log buffer."""
    try:
        for raw in iter(pipe.readline, ''):
            _append_log(raw.rstrip('\n'))
    except (ValueError, OSError):
        pass  # pipe closed when process is killed


def _record_course_result(classname, exit_code, failed_count, download_path):
    """Persist the last download result for a course into the local DB."""
    with _db_lock:
        courses = db.read('downloaded_courses') or {}
        courses[classname] = {
            'status': 'completed' if exit_code == 0 and failed_count == 0
                      else 'partial',
            'finished_at': time.time(),
            'failed': failed_count,
            'path': download_path,
        }
        if 'downloaded_courses' in db._data:
            db.update('downloaded_courses', courses)
        else:
            db.create('downloaded_courses', courses)


def _count_course_files(download_path, classname):
    """Count files on disk under <download_path>/<classname>/."""
    course_dir = os.path.join(download_path, classname)
    if not os.path.isdir(course_dir):
        return 0
    count = 0
    for _root, _dirs, files in os.walk(course_dir):
        count += len(files)
    return count


def _run_download(cmd):
    with _state_lock:
        _state['running'] = True
        _state['exit_code'] = None
        _state['started_at'] = time.time()
        _state['finished_at'] = None
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
            _state['finished_at'] = time.time()
            failed_count = len(_state['failed_urls'])
            # cmd layout: [python, start.py, classname, -ca, cauth, --path, path, ...]
            classname = cmd[2] if len(cmd) > 2 else ''
            download_path = cmd[6] if len(cmd) > 6 and cmd[5] == '--path' else ''
        try:
            _record_course_result(classname, code, failed_count, download_path)
        except Exception as exc:
            _append_log('[webgui] failed to record course result: %s' % exc)
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


@app.route('/api/course-status')
def api_course_status():
    """Check whether a course was already downloaded (DB + disk).

    The DB alone can go stale — the download folder may have been deleted —
    so the answer is only "downloaded" when both the DB record exists and
    the course folder still contains files.
    """
    course = (request.args.get('course') or '').strip()
    if not course:
        return jsonify({'downloaded': False})
    classname = general.urltoclassname(course)
    if not classname:
        return jsonify({'downloaded': False})
    with _db_lock:
        record = (db.read('downloaded_courses') or {}).get(classname)
    if not record:
        return jsonify({'downloaded': False})
    download_path = record.get('path') or (db.read('argdict') or {}).get('path') or ''
    files_on_disk = _count_course_files(download_path, classname)
    if files_on_disk == 0:
        # Folder was deleted; drop the stale record so the check reflects
        # reality on the next query.
        with _db_lock:
            courses = db.read('downloaded_courses') or {}
            courses.pop(classname, None)
            if 'downloaded_courses' in db._data:
                db.update('downloaded_courses', courses)
        return jsonify({'downloaded': False, 'stale_cleared': True})
    return jsonify({
        'downloaded': True,
        'status': record.get('status'),
        'failed': record.get('failed', 0),
        'finished_at': record.get('finished_at'),
        'files_on_disk': files_on_disk,
    })


@app.route('/api/courses')
def api_courses():
    """List all recorded downloaded courses, verified against the disk."""
    with _db_lock:
        courses = dict(db.read('downloaded_courses') or {})
    rows = []
    for classname, record in sorted(courses.items()):
        download_path = record.get('path') or (db.read('argdict') or {}).get('path') or ''
        files_on_disk = _count_course_files(download_path, classname)
        row = {
            'course': classname,
            'status': record.get('status'),
            'failed': record.get('failed', 0),
            'finished_at': record.get('finished_at'),
            'path': download_path,
            'files_on_disk': files_on_disk,
            'on_disk': files_on_disk > 0,
        }
        rows.append(row)
    return jsonify({'courses': rows})


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

    cmd = _build_cmd(classname, cauth, download_path,
                     data.get('resolution') or '720p', lang_name,
                     bool(data.get('resume')))

    with _state_lock:
        _state['logs'].clear()
        _state['log_offset'] = 0
        _state['failed_urls'] = []
        _state['stats'] = {'downloaded': 0, 'skipped': 0}
        _state['started_at'] = None
        _state['finished_at'] = None

    threading.Thread(target=_run_download, args=(cmd,), daemon=True).start()
    return jsonify({'ok': True, 'course': classname})


def _build_cmd(classname, cauth, download_path, resolution, lang_name, resume):
    lang_code = general.LANG_NAME_TO_CODE_MAPPING.get(lang_name, 'en')

    cmd = [PYTHON, 'start.py', classname,
           '-ca', cauth,
           '--path', download_path,
           '--video-resolution', resolution,
           '-sl', lang_code,
           '--download-quizzes',
           '--download-notebooks',
           '--playlist',
           '--jobs', '1']
    if resume:
        cmd += ['--resume', '--cache-syllabus']
    return cmd


@app.route('/api/update', methods=['POST'])
def api_update():
    """Re-run the download for an already-recorded course.

    Same as /api/retry but works for any recorded course, not just the last
    run with failures: existing files on disk are skipped, so only content
    that is new (e.g. newly supported item types) gets downloaded.
    """
    data = request.get_json(force=True) or {}
    course = (data.get('course') or '').strip()
    if not course:
        return jsonify({'ok': False, 'error': 'Course is required'}), 400

    classname = general.urltoclassname(course)
    if not classname:
        return jsonify({'ok': False, 'error': 'Invalid course slug or URL'}), 400

    cauth = (db.read('webgui') or {}).get('cauth', '')
    if not cauth:
        return jsonify({'ok': False, 'error': 'CAUTH not saved, run a download first'}), 400

    with _db_lock:
        record = (db.read('downloaded_courses') or {}).get(classname)
    download_path = (record or {}).get('path') or (db.read('argdict') or {}).get('path') or ''
    if not download_path or not os.path.isdir(download_path):
        return jsonify({'ok': False, 'error': 'Download folder missing: %s' % download_path}), 400

    with _state_lock:
        if _state['running']:
            return jsonify({'ok': False, 'error': 'A download is already running'}), 409

    # Sync form fields so the UI shows what is being re-checked
    db.update('argdict.classname', course)
    db.update('argdict.path', download_path)

    resolution = ((db.read('argdict') or {}).get('video_resolution') or '720p')
    lang_name = (db.read('argdict') or {}).get('sl') or 'English'

    cmd = _build_cmd(classname, cauth, download_path, resolution,
                     lang_name, False)

    with _state_lock:
        _state['logs'].clear()
        _state['log_offset'] = 0
        _state['failed_urls'] = []
        _state['stats'] = {'downloaded': 0, 'skipped': 0}
        _state['started_at'] = None
        _state['finished_at'] = None

    threading.Thread(target=_run_download, args=(cmd,), daemon=True).start()
    return jsonify({'ok': True, 'course': classname})


@app.route('/api/retry', methods=['POST'])
def api_retry():
    """Re-run the last download with the saved settings.

    CourseraDownloader skips files that already exist on disk, so a re-run
    only fetches the files that failed (or were missing) last time.
    """
    cauth = (db.read('webgui') or {}).get('cauth', '')
    if not cauth:
        return jsonify({'ok': False, 'error': 'CAUTH not saved, run a download first'}), 400

    argdict = db.read('argdict') or {}
    course = (argdict.get('classname') or '').strip()
    download_path = (argdict.get('path') or '').strip()
    if not course or not download_path or not os.path.isdir(download_path):
        return jsonify({'ok': False, 'error': 'No previous download to retry'}), 400

    classname = general.urltoclassname(course)
    if not classname:
        return jsonify({'ok': False, 'error': 'Invalid saved course slug'}), 400

    with _state_lock:
        if _state['running']:
            return jsonify({'ok': False, 'error': 'A download is already running'}), 409
        n_failed = len(_state['failed_urls'])
    if n_failed == 0:
        return jsonify({'ok': False, 'error': 'Nothing to retry, no failed files'}), 400

    cmd = _build_cmd(classname, cauth, download_path,
                     argdict.get('video_resolution') or '720p',
                     argdict.get('sl') or 'English', False)

    with _state_lock:
        _state['logs'].clear()
        _state['log_offset'] = 0
        _state['failed_urls'] = []
        _state['stats'] = {'downloaded': 0, 'skipped': 0}
        _state['started_at'] = None
        _state['finished_at'] = None

    threading.Thread(target=_run_download, args=(cmd,), daemon=True).start()
    return jsonify({'ok': True, 'course': classname, 'retrying': n_failed})


@app.route('/api/logs')
def api_logs():
    since = request.args.get('since', 0, type=int)
    with _state_lock:
        logs = list(_state['logs'])
        total = _state['log_offset']
        running = _state['running']
        exit_code = _state['exit_code']
        failed_urls = list(_state['failed_urls'])
        stats = dict(_state['stats'])
        started_at = _state['started_at']
        finished_at = _state['finished_at']
    # `since` is the number of lines the client already has; the deque only
    # keeps the most recent LOG_BUFFER_SIZE lines, so convert the absolute
    # offset into an index into the buffered slice.
    skip = max(0, min(since - (total - len(logs)), len(logs)))
    return jsonify({
        'lines': logs[skip:],
        'total': total,
        'running': running,
        'exit_code': exit_code,
        'failed_urls': failed_urls,
        'stats': stats,
        'started_at': started_at,
        'finished_at': finished_at,
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