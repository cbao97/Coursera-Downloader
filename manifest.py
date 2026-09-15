"""Course manifest (course.json) for tg-drive.

Walks the same hierarchy the downloader walks (_iter_modules) so the
filenames recorded in the manifest are exactly the filenames the
downloader writes to disk. Readable module/lesson titles come from the
extractor's readable names (written as <class>-titles-parsed.json by
extractors.py at parse time); missing entries fall back to a best-effort
title derived from the slug.

Retro-fit an already downloaded course (syllabus cache must be in cwd):
    python -m manifest <path> <class_name>
"""
import json
import logging
import os

from utils import slurp_json, spit_json
from workflow import _iter_modules

MANIFEST_NAME = 'course.json'

# fmt -> manifest lesson type. Video wins over reading when both present.
_TYPE_BY_FMT = (
    (('mp4',), 'video'),
    (('html', 'pdf'), 'reading'),
)

# candidate fmts used to record a filename per lesson type, in priority order
_FILE_FMT = {'video': ('mp4',), 'reading': ('html', 'pdf')}


def title_from_slug(slug):
    """'course-introduction' -> 'Course introduction'. Best effort."""
    words = [w.lower() for w in slug.replace('_', '-').split('-') if w]
    if not words:
        return slug
    words[0] = words[0][:1].upper() + words[0][1:]
    return ' '.join(words)


def _lesson_type(fmts):
    for keys, kind in _TYPE_BY_FMT:
        if any(k in fmts for k in keys):
            return kind
    return 'asset'


def _lookup_title(titles, module_slug, item_slug):
    mod = titles.get(module_slug) or {}
    if item_slug:
        name = (mod.get('items') or {}).get(item_slug)
        if name:
            return name
    return title_from_slug(item_slug or module_slug)


class _DefaultArgs(object):
    """Minimal args stub for CLI/retro runs (filters disabled)."""
    file_formats = None
    lecture_filter = None
    resource_filter = None
    section_filter = None
    verbose_dirs = False
    combined_section_lectures_nums = False


def build_manifest(modules, titles, class_name, path, args):
    """Build the manifest dict from the parsed syllabus.

    `titles` maps module slug -> {'name': str, 'items': {slug: str}},
    or None when unavailable.
    """
    titles = titles or {}
    args = args or _DefaultArgs()
    result = {'version': 1, 'modules': []}
    base = os.path.join(path, class_name)

    for module in _iter_modules(modules, class_name, path, [], args):
        module_slug = module._module[0]
        mod_titles = titles.get(module_slug) or {}
        lessons = []
        for section in module.sections:
            for lecture in section.lectures:
                # IterLecture._lecture is the raw assets dict
                # ({fmt: [[url, title], ...]}); fmts decide the type.
                fmts = set(lecture._lecture.keys())
                kind = _lesson_type(fmts)
                lesson = {
                    'n': lecture.index + 1,
                    'slug': lecture.name,
                    'title': _lookup_title(titles, module_slug, lecture.name),
                    'type': kind,
                }
                for fmt in _FILE_FMT.get(kind, ()):
                    if fmt in fmts:
                        lesson['file'] = os.path.relpath(
                            lecture.filename(fmt, ''),
                            base).replace(os.sep, '/')
                        break
                lessons.append(lesson)
        result['modules'].append({
            'n': module.index + 1,
            'slug': module_slug,
            'title': mod_titles.get('name') or title_from_slug(module_slug),
            'lessons': lessons,
        })
    return result


def write_manifest(path, class_name, modules, titles, args):
    """Build the manifest and write course.json into the course folder."""
    from utils import mkdir_p
    manifest = build_manifest(modules, titles, class_name, path, args)
    course_dir = os.path.join(path, class_name)
    mkdir_p(course_dir)
    out = os.path.join(course_dir, MANIFEST_NAME)
    spit_json(manifest, out)
    logging.info('Course manifest written to %s', out)
    return out


def load_titles(class_name):
    titles_file = '%s-titles-parsed.json' % class_name
    if os.path.isfile(titles_file):
        return slurp_json(titles_file)
    return None


def main():
    import sys
    if len(sys.argv) != 3:
        print('Usage: python -m manifest <path> <class_name>')
        return 1
    path, class_name = sys.argv[1], sys.argv[2]
    syllabus_file = '%s-syllabus-parsed.json' % class_name
    if not os.path.isfile(syllabus_file):
        print('Missing %s in cwd — re-run the downloader with '
              '--cache-syllabus first' % syllabus_file)
        return 1
    modules = slurp_json(syllabus_file)
    out = write_manifest(path, class_name, modules, load_titles(class_name),
                         None)
    print('Wrote %s' % out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
