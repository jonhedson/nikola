# -*- coding: utf-8 -*-

# Copyright © 2012-2014 Roberto Alsina and others.

# Permission is hereby granted, free of charge, to any
# person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the
# Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the
# Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice
# shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from __future__ import unicode_literals, print_function
import codecs
import datetime
import os
import sys

from blinker import signal

from nikola.plugin_categories import Command
from nikola import utils

LOGGER = utils.get_logger('new', utils.STDERR_HANDLER)


def filter_post_pages(compiler, is_post, compilers, post_pages):
    """Given a compiler ("markdown", "rest"), and whether it's meant for
    a post or a page, and compilers, return the correct entry from
    post_pages."""

    # First throw away all the post_pages with the wrong is_post
    filtered = [entry for entry in post_pages if entry[3] == is_post]

    # These are the extensions supported by the required format
    extensions = compilers[compiler]

    # Throw away the post_pages with the wrong extensions
    filtered = [entry for entry in filtered if any([ext in entry[0] for ext in
                                                    extensions])]

    if not filtered:
        type_name = "post" if is_post else "page"
        raise Exception("Can't find a way, using your configuration, to create "
                        "a {0} in format {1}. You may want to tweak "
                        "COMPILERS or {2}S in conf.py".format(
                            type_name, compiler, type_name.upper()))
    return filtered[0]


def get_default_compiler(is_post, compilers, post_pages):
    """Given compilers and post_pages, return a reasonable
    default compiler for this kind of post/page.
    """

    # First throw away all the post_pages with the wrong is_post
    filtered = [entry for entry in post_pages if entry[3] == is_post]

    # Get extensions in filtered post_pages until one matches a compiler
    for entry in filtered:
        extension = os.path.splitext(entry[0])[-1]
        for compiler, extensions in compilers.items():
            if extension in extensions:
                return compiler
    # No idea, back to default behaviour
    return 'rest'


def get_date(schedule=False, rule=None, last_date=None, force_today=False):
    """Returns a date stamp, given a recurrence rule.

    schedule - bool:
        whether to use the recurrence rule or not

    rule - str:
        an iCal RRULE string that specifies the rule for scheduling posts

    last_date - datetime:
        timestamp of the last post

    force_today - bool:
        tries to schedule a post to today, if possible, even if the scheduled
        time has already passed in the day.
    """

    date = now = datetime.datetime.now()
    if schedule:
        try:
            from dateutil import rrule
        except ImportError:
            utils.req_missing(['dateutil'], 'use the --schedule switch')
            rrule = None
    if schedule and rrule and rule:
        if last_date and last_date.tzinfo:
            # strip tzinfo for comparisons
            last_date = last_date.replace(tzinfo=None)
        try:
            rule_ = rrule.rrulestr(rule, dtstart=last_date)
        except Exception:
            LOGGER.error('Unable to parse rule string, using current time.')
        else:
            # Try to post today, instead of tomorrow, if no other post today.
            if force_today:
                now = now.replace(hour=0, minute=0, second=0, microsecond=0)
            date = rule_.after(max(now, last_date or now), last_date is None)
    return date.strftime('%Y/%m/%d %H:%M:%S')


class CommandNew(Command):
    """Create a new item."""

    name = "new"
    doc_usage = "[options] (post|page) [path]"
    doc_purpose = "create a new blog post or site page"
    cmd_options = [
        {
            'name': 'title',
            'short': 't',
            'long': 'title',
            'type': str,
            'default': '',
            'help': 'Title for the page/post.'
        },
        {
            'name': 'tags',
            'long': 'tags',
            'type': str,
            'default': '',
            'help': 'Comma-separated tags for the page/post.'
        },
        {
            'name': 'onefile',
            'short': '1',
            'type': bool,
            'default': False,
            'help': 'Create post with embedded metadata (single file format)'
        },
        {
            'name': 'twofile',
            'short': '2',
            'type': bool,
            'default': False,
            'help': 'Create post with separate metadata (two file format)'
        },
        {
            'name': 'post_format',
            'short': 'f',
            'long': 'format',
            'type': str,
            'default': '',
            'help': 'Markup format for post, one of rest, markdown, wiki, '
                    'bbcode, html, textile, txt2tags',
        },
        {
            'name': 'schedule',
            'short': 's',
            'type': bool,
            'default': False,
            'help': 'Schedule post based on recurrence rule'
        },

    ]

    def _execute(self, options, args):
        """Create a new post or page."""
        compiler_names = [p.name for p in
                          self.site.plugin_manager.getPluginsOfCategory(
                              "PageCompiler")]

        if len(args) == 2:
            # post/page, path
            path = args[1]
        elif len(args) == 1:
            # post/page
            path = None
        else:
            # none || too many
            print(self.help())
            return False

        is_page = args[0] == 'page'
        is_post = not is_page
        content_type = 'page' if is_page else 'post'
        title = options['title'] or None
        tags = options['tags']
        onefile = options['onefile']
        twofile = options['twofile']

        if twofile:
            onefile = False
        if not onefile and not twofile:
            onefile = self.site.config.get('ONE_FILE_POSTS', True)

        post_format = options['post_format']

        if not post_format:  # Issue #400
            post_format = get_default_compiler(
                is_post,
                self.site.config['COMPILERS'],
                self.site.config['post_pages'])

        if post_format not in compiler_names:
            LOGGER.error("Unknown post format " + post_format)
            return
        compiler_plugin = self.site.plugin_manager.getPluginByName(
            post_format, "PageCompiler").plugin_object

        # Guess where we should put this
        entry = filter_post_pages(post_format, is_post,
                                  self.site.config['COMPILERS'],
                                  self.site.config['post_pages'])

        # Create a nice underscore for the creation message
        underscore = '-' * len(content_type)

        print("Creating New {0}".format(content_type.title()))
        print("-------------{0}\n".format(underscore))
        if title is None:
            print("Enter title: ", end='')
            # WHY, PYTHON3???? WHY?
            sys.stdout.flush()
            title = sys.stdin.readline()
        else:
            print("Title:", title)
        if isinstance(title, utils.bytes_str):
            title = title.decode(sys.stdin.encoding)
        title = title.strip()
        if not path:
            slug = utils.slugify(title)
        else:
            if isinstance(path, utils.bytes_str):
                path = path.decode(sys.stdin.encoding)
            slug = utils.slugify(os.path.splitext(os.path.basename(path))[0])
        # Calculate the date to use for the post
        schedule = options['schedule'] or self.site.config['SCHEDULE_ALL']
        rule = self.site.config['SCHEDULE_RULE']
        force_today = self.site.config['SCHEDULE_FORCE_TODAY']
        self.site.scan_posts()
        timeline = self.site.timeline
        last_date = None if not timeline else timeline[0].date
        date = get_date(schedule, rule, last_date, force_today)
        data = [title, slug, date, tags]
        output_path = os.path.dirname(entry[0])
        meta_path = os.path.join(output_path, slug + ".meta")
        pattern = os.path.basename(entry[0])
        suffix = pattern[1:]
        if not path:
            txt_path = os.path.join(output_path, slug + suffix)
        else:
            txt_path = path

        if (not onefile and os.path.isfile(meta_path)) or \
                os.path.isfile(txt_path):
            LOGGER.error("The title already exists!")
            exit()

        d_name = os.path.dirname(txt_path)
        utils.makedirs(d_name)
        metadata = self.site.config['ADDITIONAL_METADATA']
        compiler_plugin.create_post(
            txt_path, onefile, title=title,
            slug=slug, date=date, tags=tags, **metadata)

        event = dict(path=txt_path)

        if not onefile:  # write metadata file
            with codecs.open(meta_path, "wb+", "utf8") as fd:
                fd.write('\n'.join(data))
            with codecs.open(txt_path, "wb+", "utf8") as fd:
                fd.write("Write your {0} here.".format(content_type))
            LOGGER.info("Your {0}'s metadata is at: {1}".format(content_type, meta_path))
            event['meta_path'] = meta_path
        LOGGER.info("Your {0}'s text is at: {1}".format(content_type, txt_path))

        signal('new_post').send(self, **event)