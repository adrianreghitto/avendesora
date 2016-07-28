# Abraxas Password Writers
#
# Given a secret (password or passphrase) the writer is responsible for getting 
# it to the user in a reasonably secure manner.
#
# Copyright (C) 2016 Kenneth S. Kundert and Kale Kundert

# License {{{1
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see http://www.gnu.org/licenses/.

# Imports {{{1
from . import cursor
from .config import get_setting
from .preferences import INITIAL_AUTOTYPE_DELAY
from shlib import Run
from inform import Color, Error, error, fatal, log, output, warn
from time import sleep
from textwrap import indent, dedent
import string
import re

# Globals {{{1
LabelColor = Color(
    color=get_setting('label_color'),
    scheme=get_setting('color_scheme'),
    enable=Color.isTTY()
)
KEYSYMS = {
    '!': 'exclam',
    '"': 'quotedbl',
    '#': 'numbersign',
    '$': 'dollar',
    '%': 'percent',
    '&': 'ampersand',
    "'": 'apostrophe',
    '(': 'parenleft',
    ')': 'parenright',
    '*': 'asterisk',
    '+': 'plus',
    ',': 'comma',
    '-': 'minus',
    '.': 'period',
    '/': 'slash',
    '0': 'zero',
    '1': 'one',
    '2': 'two',
    '3': 'three',
    '4': 'four',
    '5': 'five',
    '6': 'six',
    '7': 'seven',
    '8': 'eight',
    '9': 'nine',
    ' ': 'space',
    ':': 'colon',
    ';': 'semicolon',
    '<': 'less',
    '=': 'equal',
    '>': 'greater',
    '?': 'question',
    '@': 'at',
    '[': 'bracketleft',
    '\\': 'backslash',
    ']': 'bracketright',
    '^': 'asciicircum',
    '_': 'underscore',
    '`': 'grave',
    '{': 'braceleft',
    '|': 'bar',
    '}': 'braceright',
    '~': 'asciitilde',
    '\n': 'Return',
    '\t': 'Tab',
}

# Writer selection {{{1
def get_writer(display=True, clipboard=False, stdout=False):
    if not display:
        return KeyboardWriter()
    elif clipboard:
        return ClipboardWriter()
    elif stdout:
        return StdoutWriter()
    return TTY_Writer()

# Writer base class {{{1
class Writer:
    pass


# TTY_Writer class {{{1
class TTY_Writer(Writer):
    """Writes output to the user's TTY."""

    def display_field(self, account, field):
        name, key = account.split_name(field)
        is_secret = account.is_secret(name, key)
        try:
            value = account.get_field(name, key)
            tvalue = dedent(str(value)).strip()
        except Error as err:
            err.terminate()
        sep = ' '
        if '\n' in tvalue:
            if is_secret:
                warn(
                    'secret contains newlines, will not be fully concealed.',
                    culprit=key
                )
            else:
                tvalue = indent(dedent(tvalue), get_setting('indent')).strip('\n')
                sep = '\n'

        # build output string
        label = account.combine_name(name, key)
        log('Writing to TTY:', label)
        label = label.upper()
        try:
            alt_name = value.get_name()
            if alt_name:
                label += ' (%s)' % value.get_name()
        except AttributeError:
            pass
        text = LabelColor(label + ':') + sep + tvalue

        if is_secret:
            try:
                cursor.write(text + ' ')
                sleep(get_setting('display_time'))
                cursor.clear()
            except KeyboardInterrupt:
                cursor.clear()
        else:
            output(text)


# ClipboardWriter class {{{1
class ClipboardWriter(Writer):
    """Writes output to the system clipboard."""

    def display_field(self, account, field):
        name, key = account.split_name(field)
        is_secret = account.is_secret(name, key)
        try:
            value = dedent(str(account.get_field(name, key))).strip()
        except Error as err:
            err.terminate()

        # Use 'xsel' to put the information on the clipboard.
        # This represents a vulnerability, if someone were to replace xsel they
        # could steal my passwords. This is why I use an absolute path. I tried
        # to access the clipboard directly using GTK but I cannot get the code
        # to work.

        log('Writing to clipboard.')
        try:
            Run(
                [get_settings('xsel_executable'), '-b', '-i'],
                'soew',
                stdin=value
            )
        except Error as err:
            err.terminate()

        if is_secret:
            # produce count down
            try:
                for t in range(get_setting('display_time'), -1, -1):
                    cursor.write(str(t))
                    sleep(1)
                    cursor.clear()
            except KeyboardInterrupt:
                cursor.clear()

            # clear the clipboard
            try:
                Run([get_settings('xsel_executable'), '-b', '-c'], 'soew')
            except Error as err:
                err.terminate()

        # Use Gobject Introspection (GTK) to put the information on the
        # clipboard (for some reason I cannot get this to work).
        #try:
        #    from gi.repository import Gtk, Gdk
        #
        #    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        #    clipboard.set_text(text, len(text))
        #    clipboard.store()
        #    sleep(self.wait)
        #    clipboard.clear()
        #except ImportError:
        #    error('Clipboard is not supported.')


# StdoutWriter class {{{1
class StdoutWriter(Writer):
    """Writes to the standard output."""

    def display_field(self, account, field):
        try:
            print(dedent(str(account.get_value(field))).strip())
        except Error as err:
            err.terminate()


# KeyboardWriter class {{{1
class KeyboardWriter(Writer):
    """Writes output via pseudo-keyboard."""

    def run_script(self, account, script):

        def run_xdotool(args):
            try:
                #[get_setting('xdotool_executable'), 'getactivewindow'] +
                Run([get_setting('xdotool_executable')] + args, 'soeW')
            except OSError as err:
                fatal(os_error(err))

        def autotype(text):
            # Split the text into individual key strokes and convert the special
            # characters to their xkeysym names
            keysyms = []
            for char in text:
                if char in string.ascii_letters:
                    keysym = char
                else:
                    keysym = KEYSYMS.get(char)
                if not keysym:
                    error('cannot map to keysym, unknown', culprit=char)
                else:
                    keysyms.append(keysym)
            run_xdotool('key --clearmodifiers'.split() + keysyms)

        # Create the default script if a script was not given
        if script is True:
            # this bit of trickery gets the name of the default field
            name, key = account.split_name(None)
            name = account.combine_name(name, key)
            script = "{%s}{return}" % name

        # Run the script
        regex = re.compile(r'({\w+})')
        out = []
        scrubbed = []
        sleep(INITIAL_AUTOTYPE_DELAY)
        for term in regex.split(script):
            if term and term[0] == '{' and term[-1] == '}':
                # we have found a command
                cmd = term[1:-1].lower()
                if cmd == 'tab':
                    out.append('\t')
                    scrubbed.append('\t')
                elif cmd == 'return':
                    out.append('\n')
                    scrubbed.append('\n')
                elif cmd.startswith('sleep '):
                    cmd = cmd.split()
                    try:
                        assert cmd[0] == 'sleep'
                        assert len(cmd) == 2
                        if out:
                            autotype(''.join(out))
                            out = []
                        sleep(cmd[1])
                        scrubbed.append('<sleep %s>' % cmd[1])
                    except (AssertionError, TypeError):
                        fatal('syntax error in keyboard script.', culprit=term)
                else:
                    name, key = account.split_name(cmd)
                    try:
                        value = dedent(str(account.get_field(name, key))).strip()
                        out.append(value)
                        if account.is_secret(name, key):
                            scrubbed.append('<%s>' % cmd)
                        else:
                            scrubbed.append('%s' % value)
                    except Error as err:
                        err.terminate()
            else:
                out.append(term)
        log('Autotyping "%s".' % ''.join(scrubbed))
        autotype(''.join(out))


