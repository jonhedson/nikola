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
import os
import re
import sys
from lxml import etree

try:
    from urlparse import urlparse
    from urllib import unquote
except ImportError:
    from urllib.parse import urlparse, unquote  # NOQA

try:
    import requests
except ImportError:
    requests = None  # NOQA

try:
    import phpserialize
except ImportError:
    phpserialize = None  # NOQA

from nikola.plugin_categories import Command
from nikola import utils
from nikola.utils import req_missing
from nikola.plugins.basic_import import ImportMixin, links
from nikola.nikola import DEFAULT_TRANSLATIONS_PATTERN

LOGGER = utils.get_logger('import_wordpress', utils.STDERR_HANDLER)


class CommandImportWordpress(Command, ImportMixin):
    """Import a WordPress dump."""

    name = "import_wordpress"
    needs_config = False
    doc_usage = "[options] wordpress_export_file"
    doc_purpose = "import a WordPress dump"
    cmd_options = ImportMixin.cmd_options + [
        {
            'name': 'exclude_drafts',
            'long': 'no-drafts',
            'short': 'd',
            'default': False,
            'type': bool,
            'help': "Don't import drafts",
        },
        {
            'name': 'squash_newlines',
            'long': 'squash-newlines',
            'default': False,
            'type': bool,
            'help': "Shorten multiple newlines in a row to only two newlines",
        },
        {
            'name': 'no_downloads',
            'long': 'no-downloads',
            'default': False,
            'type': bool,
            'help': "Do not try to download files for the import",
        },
        {
            'name': 'separate_qtranslate_content',
            'long': 'qtranslate',
            'default': False,
            'type': bool,
            'help': "Look for translations generated by qtranslate plugin",
            # WARNING: won't recover translated titles that actually
            # don't seem to be part of the wordpress XML export at the
            # time of writing :(
        },
        {
            'name': 'translations_pattern',
            'long': 'translations_pattern',
            'default': None,
            'type': str,
            'help': "The pattern for translation files names",
        },
    ]

    def _execute(self, options={}, args=[]):
        """Import a WordPress blog from an export file into a Nikola site."""
        if not args:
            print(self.help())
            return

        options['filename'] = args.pop(0)

        if args and ('output_folder' not in args or
                     options['output_folder'] == 'new_site'):
            options['output_folder'] = args.pop(0)

        if args:
            LOGGER.warn('You specified additional arguments ({0}). Please consider '
                        'putting these arguments before the filename if you '
                        'are running into problems.'.format(args))

        self.import_into_existing_site = False
        self.url_map = {}
        self.timezone = None

        self.wordpress_export_file = options['filename']
        self.squash_newlines = options.get('squash_newlines', False)
        self.output_folder = options.get('output_folder', 'new_site')

        self.exclude_drafts = options.get('exclude_drafts', False)
        self.no_downloads = options.get('no_downloads', False)

        self.separate_qtranslate_content = options.get('separate_qtranslate_content')
        self.translations_pattern = options.get('translations_pattern')

        if not self.no_downloads:
            def show_info_about_mising_module(modulename):
                LOGGER.error(
                    'To use the "{commandname}" command, you have to install '
                    'the "{package}" package or supply the "--no-downloads" '
                    'option.'.format(
                        commandname=self.name,
                        package=modulename)
                )

            if requests is None and phpserialize is None:
                req_missing(['requests', 'phpserialize'], 'import WordPress dumps without --no-downloads')
            elif requests is None:
                req_missing(['requests'], 'import WordPress dumps without --no-downloads')
            elif phpserialize is None:
                req_missing(['phpserialize'], 'import WordPress dumps without --no-downloads')

        channel = self.get_channel_from_file(self.wordpress_export_file)
        self.context = self.populate_context(channel)
        conf_template = self.generate_base_site()

        # If user  has specified a custom pattern for translation files we
        # need to fix the config
        if self.translations_pattern:
            self.context['TRANSLATIONS_PATTERN'] = self.translations_pattern

        self.import_posts(channel)

        self.context['REDIRECTIONS'] = self.configure_redirections(
            self.url_map)
        self.write_urlmap_csv(
            os.path.join(self.output_folder, 'url_map.csv'), self.url_map)
        rendered_template = conf_template.render(**self.context)
        rendered_template = re.sub('# REDIRECTIONS = ', 'REDIRECTIONS = ',
                                   rendered_template)

        if self.timezone:
            rendered_template = re.sub('# TIMEZONE = \'UTC\'',
                                       'TIMEZONE = \'' + self.timezone + '\'',
                                       rendered_template)
        self.write_configuration(self.get_configuration_output_path(),
                                 rendered_template)

    @classmethod
    def _glue_xml_lines(cls, xml):
        new_xml = xml[0]
        previous_line_ended_in_newline = new_xml.endswith(b'\n')
        previous_line_was_indentet = False
        for line in xml[1:]:
            if (re.match(b'^[ \t]+', line) and previous_line_ended_in_newline):
                new_xml = b''.join((new_xml, line))
                previous_line_was_indentet = True
            elif previous_line_was_indentet:
                new_xml = b''.join((new_xml, line))
                previous_line_was_indentet = False
            else:
                new_xml = b'\n'.join((new_xml, line))
                previous_line_was_indentet = False

            previous_line_ended_in_newline = line.endswith(b'\n')

        return new_xml

    @classmethod
    def read_xml_file(cls, filename):
        xml = []

        with open(filename, 'rb') as fd:
            for line in fd:
                # These explode etree and are useless
                if b'<atom:link rel=' in line:
                    continue
                xml.append(line)

        return cls._glue_xml_lines(xml)

    @classmethod
    def get_channel_from_file(cls, filename):
        tree = etree.fromstring(cls.read_xml_file(filename))
        channel = tree.find('channel')
        return channel

    @staticmethod
    def populate_context(channel):
        wordpress_namespace = channel.nsmap['wp']

        context = {}
        context['DEFAULT_LANG'] = get_text_tag(channel, 'language', 'en')[:2]
        context['TRANSLATIONS_PATTERN'] = DEFAULT_TRANSLATIONS_PATTERN
        context['BLOG_TITLE'] = get_text_tag(channel, 'title',
                                             'PUT TITLE HERE')
        context['BLOG_DESCRIPTION'] = get_text_tag(
            channel, 'description', 'PUT DESCRIPTION HERE')
        context['BASE_URL'] = get_text_tag(channel, 'link', '#')
        if not context['BASE_URL']:
            base_site_url = channel.find('{{{0}}}author'.format(wordpress_namespace))
            context['BASE_URL'] = get_text_tag(base_site_url,
                                               None,
                                               "http://foo.com/")
        if not context['BASE_URL'].endswith('/'):
            context['BASE_URL'] += '/'
        context['SITE_URL'] = context['BASE_URL']
        context['THEME'] = 'bootstrap3'

        context['COMMENT_SYSTEM'] = 'disqus'
        context['COMMENT_SYSTEM_ID'] = 'nikolademo'

        author = channel.find('{{{0}}}author'.format(wordpress_namespace))
        context['BLOG_EMAIL'] = get_text_tag(
            author,
            '{{{0}}}author_email'.format(wordpress_namespace),
            "joe@example.com")
        context['BLOG_AUTHOR'] = get_text_tag(
            author,
            '{{{0}}}author_display_name'.format(wordpress_namespace),
            "Joe Example")
        context['POSTS'] = '''(
            ("posts/*.wp", "posts", "post.tmpl"),
        )'''
        context['PAGES'] = '''(
            ("stories/*.wp", "stories", "story.tmpl"),
        )'''
        context['COMPILERS'] = '''{
        "rest": ('.txt', '.rst'),
        "markdown": ('.md', '.mdown', '.markdown', '.wp'),
        "html": ('.html', '.htm')
        }
        '''

        return context

    def download_url_content_to_file(self, url, dst_path):
        if self.no_downloads:
            return

        try:
            with open(dst_path, 'wb+') as fd:
                fd.write(requests.get(url).content)
        except requests.exceptions.ConnectionError as err:
            LOGGER.warn("Downloading {0} to {1} failed: {2}".format(url, dst_path, err))

    def import_attachment(self, item, wordpress_namespace):
        url = get_text_tag(
            item, '{{{0}}}attachment_url'.format(wordpress_namespace), 'foo')
        link = get_text_tag(item, '{{{0}}}link'.format(wordpress_namespace),
                            'foo')
        path = urlparse(url).path
        dst_path = os.path.join(*([self.output_folder, 'files']
                                  + list(path.split('/'))))
        dst_dir = os.path.dirname(dst_path)
        utils.makedirs(dst_dir)
        LOGGER.info("Downloading {0} => {1}".format(url, dst_path))
        self.download_url_content_to_file(url, dst_path)
        dst_url = '/'.join(dst_path.split(os.sep)[2:])
        links[link] = '/' + dst_url
        links[url] = '/' + dst_url

        self.download_additional_image_sizes(
            item,
            wordpress_namespace,
            os.path.dirname(url)
        )

    def download_additional_image_sizes(self, item, wordpress_namespace, source_path):
        if phpserialize is None:
            return

        additional_metadata = item.findall('{{{0}}}postmeta'.format(wordpress_namespace))

        if additional_metadata is None:
            return

        for element in additional_metadata:
            meta_key = element.find('{{{0}}}meta_key'.format(wordpress_namespace))
            if meta_key is not None and meta_key.text == '_wp_attachment_metadata':
                meta_value = element.find('{{{0}}}meta_value'.format(wordpress_namespace))

                if meta_value is None:
                    continue

                # Someone from Wordpress thought it was a good idea
                # serialize PHP objects into that metadata field. Given
                # that the export should give you the power to insert
                # your blogging into another site or system its not.
                # Why don't they just use JSON?
                if sys.version_info[0] == 2:
                    metadata = phpserialize.loads(utils.sys_encode(meta_value.text))
                    size_key = 'sizes'
                    file_key = 'file'
                else:
                    metadata = phpserialize.loads(meta_value.text.encode('UTF-8'))
                    size_key = b'sizes'
                    file_key = b'file'

                if not size_key in metadata:
                    continue

                for filename in [metadata[size_key][size][file_key] for size in metadata[size_key]]:
                    url = '/'.join([source_path, filename.decode('utf-8')])

                    path = urlparse(url).path
                    dst_path = os.path.join(*([self.output_folder, 'files']
                                              + list(path.split('/'))))
                    dst_dir = os.path.dirname(dst_path)
                    utils.makedirs(dst_dir)
                    LOGGER.info("Downloading {0} => {1}".format(url, dst_path))
                    self.download_url_content_to_file(url, dst_path)
                    dst_url = '/'.join(dst_path.split(os.sep)[2:])
                    links[url] = '/' + dst_url
                    links[url] = '/' + dst_url

    @staticmethod
    def transform_sourcecode(content):
        new_content = re.sub('\[sourcecode language="([^"]+)"\]',
                             "\n~~~~~~~~~~~~{.\\1}\n", content)
        new_content = new_content.replace('[/sourcecode]',
                                          "\n~~~~~~~~~~~~\n")
        return new_content

    @staticmethod
    def transform_caption(content):
        new_caption = re.sub(r'\[/caption\]', '', content)
        new_caption = re.sub(r'\[caption.*\]', '', new_caption)

        return new_caption

    def transform_multiple_newlines(self, content):
        """Replaces multiple newlines with only two."""
        if self.squash_newlines:
            return re.sub(r'\n{3,}', r'\n\n', content)
        else:
            return content

    def transform_content(self, content):
        new_content = self.transform_sourcecode(content)
        new_content = self.transform_caption(new_content)
        new_content = self.transform_multiple_newlines(new_content)
        return new_content

    def import_item(self, item, wordpress_namespace, out_folder=None):
        """Takes an item from the feed and creates a post file."""
        if out_folder is None:
            out_folder = 'posts'

        title = get_text_tag(item, 'title', 'NO TITLE')
        # link is something like http://foo.com/2012/09/01/hello-world/
        # So, take the path, utils.slugify it, and that's our slug
        link = get_text_tag(item, 'link', None)
        path = unquote(urlparse(link).path.strip('/'))

        # In python 2, path is a str. slug requires a unicode
        # object. According to wikipedia, unquoted strings will
        # usually be UTF8
        if isinstance(path, utils.bytes_str):
            path = path.decode('utf8')
        pathlist = path.split('/')
        if len(pathlist) > 1:
            out_folder = os.path.join(*([out_folder] + pathlist[:-1]))
        slug = utils.slugify(pathlist[-1])
        if not slug:  # it happens if the post has no "nice" URL
            slug = get_text_tag(
                item, '{{{0}}}post_name'.format(wordpress_namespace), None)
        if not slug:  # it *may* happen
            slug = get_text_tag(
                item, '{{{0}}}post_id'.format(wordpress_namespace), None)
        if not slug:  # should never happen
            LOGGER.error("Error converting post:", title)
            return

        description = get_text_tag(item, 'description', '')
        post_date = get_text_tag(
            item, '{{{0}}}post_date'.format(wordpress_namespace), None)
        dt = utils.to_datetime(post_date)
        if dt.tzinfo and self.timezone is None:
            self.timezone = utils.get_tzname(dt)
        status = get_text_tag(
            item, '{{{0}}}status'.format(wordpress_namespace), 'publish')
        content = get_text_tag(
            item, '{http://purl.org/rss/1.0/modules/content/}encoded', '')

        tags = []
        if status == 'trash':
            LOGGER.warn('Trashed post "{0}" will not be imported.'.format(title))
            return
        elif status != 'publish':
            tags.append('draft')
            is_draft = True
        else:
            is_draft = False

        for tag in item.findall('category'):
            text = tag.text
            if text == 'Uncategorized':
                continue
            tags.append(text)

        if '$latex' in content:
            tags.append('mathjax')

        if is_draft and self.exclude_drafts:
            LOGGER.notice('Draft "{0}" will not be imported.'.format(title))
        elif content.strip():
            # If no content is found, no files are written.
            self.url_map[link] = (self.context['SITE_URL'] + out_folder + '/'
                                  + slug + '.html')
            if hasattr(self, "separate_qtranslate_content") \
               and self.separate_qtranslate_content:
                content_translations = separate_qtranslate_content(content)
            else:
                content_translations = {"": content}
            default_language = self.context["DEFAULT_LANG"]
            for lang, content in content_translations.items():
                if lang:
                    out_meta_filename = slug + '.meta'
                    if lang == default_language:
                        out_content_filename = slug + '.wp'
                    else:
                        out_content_filename \
                            = utils.get_translation_candidate(self.context,
                                                              slug + ".wp", lang)
                    meta_slug = slug
                else:
                    out_meta_filename = slug + '.meta'
                    out_content_filename = slug + '.wp'
                    meta_slug = slug
                content = self.transform_content(content)
                self.write_metadata(os.path.join(self.output_folder, out_folder,
                                                 out_meta_filename),
                                    title, meta_slug, post_date, description, tags)
                self.write_content(
                    os.path.join(self.output_folder,
                                 out_folder, out_content_filename),
                    content)
        else:
            LOGGER.warn('Not going to import "{0}" because it seems to contain'
                        ' no content.'.format(title))

    def process_item(self, item):
        # The namespace usually is something like:
        # http://wordpress.org/export/1.2/
        wordpress_namespace = item.nsmap['wp']
        post_type = get_text_tag(
            item, '{{{0}}}post_type'.format(wordpress_namespace), 'post')

        if post_type == 'attachment':
            self.import_attachment(item, wordpress_namespace)
        elif post_type == 'post':
            self.import_item(item, wordpress_namespace, 'posts')
        else:
            self.import_item(item, wordpress_namespace, 'stories')

    def import_posts(self, channel):
        for item in channel.findall('item'):
            self.process_item(item)


def get_text_tag(tag, name, default):
    if tag is None:
        return default
    t = tag.find(name)
    if t is not None:
        return t.text
    else:
        return default


def separate_qtranslate_content(text):
    """Parse the content of a wordpress post or page and separate
    the various language specific contents when they are delimited
    with qtranslate tags: <!--:LL-->blabla<!--:-->"""
    # TODO: uniformize qtranslate tags <!--/en--> => <!--:-->
    qt_start = "<!--:"
    qt_end = "-->"
    qt_end_with_lang_len = 5
    qt_chunks = text.split(qt_start)
    content_by_lang = {}
    common_txt_list = []
    for c in qt_chunks:
        if not c.strip():
            continue
        if c.startswith(qt_end):
            # just after the end of a language specific section, there may
            # be some piece of common text or tags, or just nothing
            lang = ""  # default language
            c = c.lstrip(qt_end)
            if not c:
                continue
        elif c[2:].startswith(qt_end):
            # a language specific section (with language code at the begining)
            lang = c[:2]
            c = c[qt_end_with_lang_len:]
        else:
            # nowhere specific (maybe there is no language section in the
            # currently parsed content)
            lang = ""  # default language
        if not lang:
            common_txt_list.append(c)
            for l in content_by_lang.keys():
                content_by_lang[l].append(c)
        else:
            content_by_lang[lang] = content_by_lang.get(lang, common_txt_list) + [c]
    # in case there was no language specific section, just add the text
    if common_txt_list and not content_by_lang:
        content_by_lang[""] = common_txt_list
    # Format back the list to simple text
    for l in content_by_lang.keys():
        content_by_lang[l] = " ".join(content_by_lang[l])
    return content_by_lang
