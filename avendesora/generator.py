# Password Generator

# License {{{1
# Copyright (C) 2016 Kenneth S. Kundert
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see http://www.gnu.org/licenses/.


# Imports {{{1
from .account import Account
from .config import get_setting
from .dictionary import DICTIONARY
from .files import AccountFile
from .gpg import GnuPG
from .preferences import (
    ACCOUNTS_FILE_INITIAL_CONTENTS, CONFIG_FILE_INITIAL_CONTENTS,
    CONFIG_FILENAME, DEFAULT_ACCOUNTS_FILENAME, DEFAULT_TEMPLATES_FILENAME,
    HASHES_FILENAME, HASH_FILE_INITIAL_CONTENTS, SETTINGS_DIR,
    TEMPLATES_FILE_INITIAL_CONTENTS,
)
from .concealers import Hidden
from .title import Title
from inform import debug, Error, fatal, terminate, terminate_if_errors
from shlib import to_path
from urllib.parse import urlparse

# Utilities {{{1
def generate_random_string(length=64):
    # Generate a random long string to act as the default password

    from string import ascii_letters, digits, punctuation
    import random
    rand = random.SystemRandom()

    # Create alphabet from letters, digits, and punctuation, but 
    # replace double quote with a space so password can be safely 
    # represented as a double-quoted string.
    alphabet = (ascii_letters + digits + punctuation).replace('"', ' ')

    password = ''
    for i in range(length):
        password += rand.choice(alphabet)
    return password


# PasswordGenerator {{{1
class PasswordGenerator:
    def __init__(self, gpg_id=None, init=False):
        self.gpg = GnuPG(gpg_id)
        self.accounts_files = []
            # don't really need to access these later, but need to keep them
            # around otherwise they will be garbage collected and we will lose
            # access to the accounts in all but the last file.

        if init:
            self.initialize()
            terminate()

        # Now open any accounts files found
        for filename in get_setting('accounts_files', []):
            try:
                path = to_path(SETTINGS_DIR, filename)
                account_file = AccountFile(path, self.gpg)
                self.accounts_files.append(account_file)
                contents = account_file.read()
                if 'master_password' in contents:
                    self.add_missing_master(contents['master_password'])
            except Error as err:
                err.terminate()
        terminate_if_errors()
        if len(self.accounts_files) == 0:
            fatal('no accounts files were specified.')

        DICTIONARY.validate(get_setting('dict_hash'))

    def initialize(self):
        def split(s, l=72):
            # Break long string into a series of adjacent shorter strings
            if len(s) < l:
                return '"%s"' % s
            chunks = ['    "%s"' % s[i:i+l] for i in range(0, len(s), l)]
            return '\n' + '\n'.join(chunks) + '\n'

        def dict_to_str(d):
            lines = ['{']
            for k in sorted(d):
                lines.append("    '%s': '%s'," % (k, d[k]))
            lines.append('}')
            return '\n'.join(lines)

        fields = {
            'dict_hash': repr(get_setting('dict_hash')),
            'secrets_hash': repr(get_setting('secrets_hash')),
            'charsets_hash': repr(get_setting('charsets_hash')),
            'accounts_file': repr(DEFAULT_ACCOUNTS_FILENAME),
            'templates_file': repr(DEFAULT_TEMPLATES_FILENAME),
            'log_file': repr(get_setting('log_file')),
            'archive_file': repr(get_setting('archive_file')),
            'gpg_id': repr(self.gpg.gpg_id),
            'gpg_home': repr(get_setting('gpg_home')),
            'gpg_armor': repr(get_setting('gpg_armor')),
            'gpg_executable': repr(get_setting('gpg_executable')),
            'default_field': repr(get_setting('default_field')),
            'default_vector_field': repr(get_setting('default_vector_field')),
            'display_time': repr(get_setting('display_time')),
            'browsers': dict_to_str(get_setting('browsers')),
            'default_browser': repr(get_setting('default_browser')),
            'required_protocols': repr(get_setting('required_protocols')),
            'xdotool_executable': repr(get_setting('xdotool_executable')),
            'xsel_executable': repr(get_setting('xsel_executable')),
            'section': '{''{''{''1',
            'master_password': split(Hidden.hide(generate_random_string(72))),
        }

        # create the config file
        path = to_path(SETTINGS_DIR, CONFIG_FILENAME)
        f = AccountFile(path, self.gpg)
        f.create(CONFIG_FILE_INITIAL_CONTENTS.format(**fields))

        # create the hashes file
        path = to_path(SETTINGS_DIR, HASHES_FILENAME.format(**fields))
        f = AccountFile(path, self.gpg)
        f.create(HASH_FILE_INITIAL_CONTENTS.format(**fields))

        # create the initial accounts file
        path = to_path(SETTINGS_DIR, DEFAULT_ACCOUNTS_FILENAME)
        f = AccountFile(path, self.gpg)
        f.create(ACCOUNTS_FILE_INITIAL_CONTENTS.format(**fields))

        # create the templates file
        path = to_path(SETTINGS_DIR, DEFAULT_TEMPLATES_FILENAME)
        f = AccountFile(path, self.gpg)
        f.create(TEMPLATES_FILE_INITIAL_CONTENTS.format(**fields))

    def get_account(self, name):
        if not name:
            raise Error('no account specified.')
        for account in Account.all_accounts():
            if account.matches_exactly(name):
                account.initialize()
                return account
        raise Error('not found.', culprit=name)

    def find_accounts(self, target):
        accounts = []
        for account in Account.all_accounts():
            if account.id_contains(target):
                accounts.append(account)
        return accounts

    def search_accounts(self, target):
        accounts = []
        for account in Account.all_accounts():
            if account.account_contains(target):
                accounts.append(account)
        return accounts

    def discover_account(self):
        # get and parse the title
        data = Title().get_data()

        # split the url into basic components if found
        url = data.get('url')
        if url:
            url = urlparse(url)
            data['protocol'] = url.scheme
            data['host'] = url.netloc
            data['path'] = url.path

        # sweep through accounts to see if any recognize this title data
        # recognizer may fund the following fields in data:
        #     rawdata: the original title
        #     title: the processed title
        #     url: the full url
        #     browser: the name of the browser
        #     protocol: the url scheme (ex. http, https, ...)
        #     host: the url host name or IP address
        #     path: the path component of the url
        #           does not include options or anchor
        for account in Account.all_accounts():
            secret = account.recognize(data)
            if secret:
                return account.get_name(), secret
        raise Error('cannot find appropriate account.')

    def add_missing_master(self, master):
        for account in Account.all_accounts():
            if not hasattr(account, 'master'):
                account.master = master
