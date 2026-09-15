"""Tests for course.json manifest generation."""
import json
import os

from manifest import build_manifest, write_manifest


class FakeArgs(object):
    path = '.'
    file_formats = None
    lecture_filter = None
    resource_filter = None
    section_filter = None
    verbose_dirs = False
    combined_section_lectures_nums = False
    ignore_formats = None


MODULES = [
    ('data-integration', [
        ('welcome-to-the-course', [
            ('course-introduction', {
                'mp4': [['https://example.com/v.mp4', '']],
                'en.srt': [['https://example.com/en.srt', '']],
            }),
            ('course-overview', {
                'html': [['#inmemory#<p>hello</p>', '']],
            }),
        ]),
    ]),
    ('data-storage', [
        ('introduction-to-storage', [
            ('raid-concepts', {
                'pdf': [['https://example.com/x.pdf', '']],
                'mp4': [['https://example.com/r.mp4', '']],
            }),
        ]),
    ]),
]

TITLES = {
    'data-integration': {
        'name': 'Data Integration',
        'items': {'course-introduction': 'Course introduction',
                  'course-overview': 'Course overview'},
    },
    'data-storage': {
        'name': 'Data Storage',
        'items': {'raid-concepts': 'RAID concepts'},
    },
}


def test_video_lesson_gets_title_type_and_relpath():
    m = build_manifest(MODULES, TITLES, 'my-course', 'out', FakeArgs())
    les = m['modules'][0]['lessons'][0]
    assert les['title'] == 'Course introduction'
    assert les['type'] == 'video'
    assert les['file'] == \
        '01_data-integration/01_welcome-to-the-course/01_course-introduction.mp4'


def test_module_titles_and_numbering():
    m = build_manifest(MODULES, TITLES, 'my-course', 'out', FakeArgs())
    assert [mod['n'] for mod in m['modules']] == [1, 2]
    assert m['modules'][1]['title'] == 'Data Storage'
    assert m['modules'][1]['lessons'][0]['n'] == 1


def test_reading_lesson_records_html_file():
    m = build_manifest(MODULES, TITLES, 'my-course', 'out', FakeArgs())
    les = m['modules'][0]['lessons'][1]
    assert les['type'] == 'reading'
    assert les['file'] == \
        '01_data-integration/01_welcome-to-the-course/02_course-overview.html'


def test_title_falls_back_to_slug_when_titles_missing():
    m = build_manifest(MODULES, None, 'my-course', 'out', FakeArgs())
    mod = m['modules'][0]
    assert mod['title'] == 'Data integration'
    assert mod['lessons'][0]['title'] == 'Course introduction'
    assert mod['lessons'][0]['slug'] == 'course-introduction'


def test_partial_titles_fall_back_per_slug():
    titles = {'data-integration': {'name': 'Data Integration', 'lessons': {}}}
    m = build_manifest(MODULES, titles, 'my-course', 'out', FakeArgs())
    assert m['modules'][0]['title'] == 'Data Integration'
    assert m['modules'][0]['lessons'][0]['title'] == 'Course introduction'


def test_write_manifest_creates_course_json(tmp_path):
    write_manifest(str(tmp_path), 'my-course', MODULES, TITLES, FakeArgs())
    out = tmp_path / 'my-course' / 'course.json'
    assert out.is_file()
    data = json.loads(out.read_text(encoding='utf-8'))
    assert data['modules'][0]['slug'] == 'data-integration'


def test_manifest_matches_real_cached_syllabus():
    """The syllabus cache checked into the repo must round-trip."""
    import utils
    modules = utils.slurp_json(
        'data-integration-storage-migration-strategies-syllabus-parsed.json')
    m = build_manifest(modules, None, 'x', 'out', FakeArgs())
    assert len(m['modules']) == 3
    videos = [l for mod in m['modules'] for l in mod['lessons'] if l['type'] == 'video']
    assert videos and all(l['file'].endswith('.mp4') for l in videos)