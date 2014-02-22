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

class CommandNewPost(Command):
    """Create a new post."""

    name = "new_post"
    doc_usage = "[options] [path]"
    doc_purpose = "[deprecated, use `new`] create a new blog post or site page"
    cmd_options = [
        {
            'name': 'is_page',
            'short': 'p',
            'long': 'page',
            'type': bool,
            'default': False,
            'help': 'Create a page instead of a blog post.'
        },
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
        p = self.site.plugin_manager.getPluginByName('new', 'Command').plugin_object
        is_page = options.get('is_page', False)
        content_type = ['page'] if is_page else ['post']
        p.execute(options, content_type + args)
