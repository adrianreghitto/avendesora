# Commands

# License {{{1
# Copyright (C) 2016-17 Kenneth S. Kundert
#
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
from .collection import Collection
from .config import get_setting, override_setting
from .editors import GenericEditor
from .error import PasswordError
from .generator import PasswordGenerator
from .gpg import GnuPG, PythonFile
from .obscure import ObscuredSecret
from .utilities import query_user, two_columns
from .writer import get_writer
from inform import (
    codicil, columns, cull, debug, error, full_stop, output, warn, conjoin,
    os_error, is_collection, indent, render, ddd, ppp, vvv
)
from shlib import chmod, cp, rm, to_path
from docopt import docopt
from textwrap import dedent
import re
import sys


# Utilities {{{1
def title(text):
    return full_stop(text[0].upper() + text[1:])


# Command base class {{{1
class Command(object):
    @classmethod
    def commands(cls):
        for cmd in cls.__subclasses__():
            assert is_collection(cmd.NAMES)
            yield cmd
            # currently only one level of subclassing is supported

    @classmethod
    def commands_sorted(cls):
        for cmd in sorted(cls.commands(), key=lambda c: c.get_name()):
            yield cmd

    @classmethod
    def find(cls, name):
        for command in cls.commands():
            if name in command.NAMES:
                return command

    @classmethod
    def execute(cls, name, args):
        if args is None:
            args = []
        command = cls.find(name)
        if not command:
            # no recognizable command was specified
            # in this case, run 'credentials' if one argument is given
            # and 'value' otherwise
            args = [name] + args
            name = 'value' if len(args) > 1 else 'credentials'
            command = cls.find(name)
            if not command:
                error('unknown command.', culprit=name)
                codicil("Use 'avendesora help' for list of available commands."),
                return
        command.run(name, args)

    @classmethod
    def summarize(cls, width=16):
        summaries = []
        for cmd in Command.commands_sorted():
            summaries.append(two_columns(', '.join(cmd.NAMES), cmd.DESCRIPTION))
        return '\n'.join(summaries)

    @classmethod
    def get_name(cls):
        return cls.NAMES[0]

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}
        """).strip()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE,
        )

    @classmethod
    def get_help_url(cls):
        try:
            anchor = '-'.join(e.lower() for e in [cls.NAMES[0]] + cls.DESCRIPTION.split())
            return '/commands.html#' + anchor
        except (AttributeError, TypeError):
            pass


# Add {{{1
class Add(Command):
    NAMES = 'add', 'a'
    DESCRIPTION = 'add a new account'
    USAGE = dedent("""
        Usage:
            avendesora add [options] [<template>]
            avendesora a   [options] [<template>]

        Options:
            -f <file>, --file <file>
                                    Add account to specified accounts file.

        Creates a new account starting from a template. The template consists of
        boilerplate code and fields. The fields take the from _NAME_. They
        should be replaced by appropriate values or deleted if not needed. If
        you are using the Vim editor, it is preconfigured to jump to the next
        field when you press 'n'.  If the field is surrounded by '<<' and '>>',
        as in '<<_ACCOUNT_NUMBER_>>', the value you enter will be concealed.

        You can create your own templates by adding them to 'account_templates'
        in the ~/.config/avendesora/config file.

        You can change the editor used when adding account by changing the
        'edit_template', also found in the ~/.config/avendesora/config file.
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            The default template is {default}. The available templates are:
            {templates}

            The available accounts files are (the default is given first):
            {files}
        """).strip()

        def indented_list(l):
            indent = get_setting('indent')
            return indent + ('\n'+indent).join(sorted(l))

        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE,
            default=get_setting('default_account_template'),
            templates=indented_list(get_setting('account_templates').keys()),
            files=indented_list(get_setting('accounts_files', [])),
        )

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # determine the accounts file
        prefix = cmdline['--file']
        if prefix:
            candidates = [
                p
                for p in get_setting('accounts_files')
                if p.startswith(prefix)
            ]
            if not candidates:
                raise PasswordError('not found.', cuplrit=cmdline['--file'])
            if len(candidates) > 1:
                raise PasswordError(
                    'ambiguous, matches %s.' % conjoin(candidates),
                    cuplrit=prefix
                )
            filename = candidates[0]
        else:
            filename = get_setting('accounts_files')[0]

        try:
            # get the specified template
            templates = get_setting('account_templates')
            if cmdline['<template>']:
                template_name = cmdline['<template>']
            else:
                template_name = get_setting('default_account_template')
            template = dedent(templates[template_name]).strip() + '\n'
        except KeyError:
            raise PasswordError(
                'unknown account template, choose from %s.' % conjoin(
                    sorted(templates.keys())
                ), culprit=template_name
            )

        try:
            # get original contents of accounts file
            path = to_path(get_setting('settings_dir'), filename)
            orig_accounts_file = PythonFile(path)
            orig_accounts = orig_accounts_file.run()
            gpg_ids = orig_accounts.get('gpg_ids')
            orig_accounts_code = orig_accounts_file.code.strip('\n')

            # backup the original file
            orig_accounts_file.backup('.saved')

            # save the template into temp file
            from tempfile import mktemp
            tmpfilename = mktemp(suffix='_avendesora.gpg')
            tmpfile = GnuPG(tmpfilename)
            tmpfile.save(template, get_setting('gpg_ids'))
        except OSError as e:
            raise PasswordError(os_error(e))

        # open template in the editor
        try:
            while (True):
                GenericEditor.open(tmpfile.path)

                # read the tmp file and determine if it has changed
                new = tmpfile.read()
                if not new.strip() or new == template:
                    return output('Unchanged, and so ignored.')
                new = tmpfile.read()

                # remove instructions
                new = '\n'.join([
                    l
                    for l in new.split('\n')
                    if not l.startswith('# Avendesora:')
                ]).strip('\n') + '\n'

                # hide the values that should be hidden
                def hide(match):
                    return 'Hidden(%r)' % ObscuredSecret.hide(match.group(1))
                new = re.sub("<<(.*?)>>", hide, new)

                # add new account to the contents
                accounts = orig_accounts_code + '\n\n\n' + new

                # save the new version
                new_accounts_file = PythonFile(path)
                new_accounts_file.save(accounts, gpg_ids)

                # check the changes to see if there are any issues
                try:
                    new_accounts_file.run()
                    break
                except PasswordError as e:
                    error(e)
                    response = query_user('Try again?')
                    if response.lower() not in ['y', 'yes']:
                        raise PasswordError(
                            'Giving up, restoring original file.'
                        )

        except (PasswordError, OSError) as e:
            orig_accounts_file.restore()
            if isinstance(e, OSError):
                e = os_error(e)
            error(e)
            codicil(
                '',
                'What you entered can be found in %s.' % tmpfilename,
                'Delete it when done with it.', sep='\n'
            )
            return

        # delete the temp file
        try:
            tmpfile.remove()
        except:
            pass


# Archive {{{1
class Archive(Command):
    NAMES = 'archive', 'A'
    DESCRIPTION = 'generates archive of all account information'
    USAGE = dedent("""
        Usage:
            avendesora archive
            avendesora A
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            This command creates an encrypted archive that contains all the
            information in your accounts files, including the fully generated
            secrets.  You should never need this file, but its presence protects
            you in case you lose access to Avendesora. To access your secrets
            without Avendesora, simply decrypt the archive file with GPG.  The
            actual secrets will be hidden, but it easy to retrieve them even
            without Avendesora. When hidden, the secrets are encoded in base64.
            You can decode it by running 'base64 -d -' and pasting the encoded
            secret into the terminal.

            When you run this command it overwrites the existing archive. If you
            have accidentally deleted an account or changed a secret, then
            replacing the archive could cause the last copy of the original
            information to be lost. To prevent this from occurring it is a good
            practice to run the 'changed' command before regenerating the
            archive.  It describes all of the changes that have occurred since
            the last time the archive was generated. You should only regenerate
            the archive once you have convinced yourself all of the changes are
            as expected.
        """).strip()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE,
        )

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)
        archive_file = get_setting('archive_file')

        # first, save existing archive if it exists
        try:
            previous_archive = get_setting('previous_archive_file')
            if previous_archive and archive_file.is_file():
                rm(previous_archive)
                cp(archive_file, previous_archive)
        except OSError as e:
            raise PasswordError(os_error(e))

        # run the generator
        generator = PasswordGenerator()

        # get dictionary that fully describes the contents of each account
        entries = []
        seen = set()
        for account in generator.all_accounts():
            name = account.get_name()
            if name in seen:
                warn('duplicate account name.', culprit=name)
            seen.add(name)
            entry = account.archive()
            if entry:
                entries.append(indent('%r: %s,' % (name, render(entry)), '    '))

        # build file contents
        from .preferences import ARCHIVE_FILE_CONTENTS
        import arrow
        contents = ARCHIVE_FILE_CONTENTS.format(
            encoding = get_setting('encoding'),
            date = str(arrow.now()),
            accounts = '\n\n'.join(entries)
        )

        archive = GnuPG(archive_file)
        if not archive.will_encrypt():
            warn('archive file is not encrypted.', culprit=archive_file)
        try:
            archive.save(contents)
            chmod(0o600, archive_file)
        except OSError as e:
            raise PasswordError(os_error(e), culprit=archive_file)


# Browse {{{1
class Browse(Command):
    NAMES = 'browse', 'b'
    DESCRIPTION = 'open account URL in web browser'
    USAGE = dedent("""
        Usage:
            avendesora browse [options] <account> [<key>]
            avendesora b      [options] <account> [<key>]

        Options:
            -b <browser>, --browser <browser>
                                    Open account in specified browser.
            -l, --list              List available URLs rather than open first.
    """).strip()

    @classmethod
    def help(cls):
        default_browser = get_setting('default_browser')
        browsers = get_setting('browsers')
        browsers = '\n'.join([
            two_columns(k, browsers[k], width=5)
            for k in sorted(browsers)
        ])
        text = dedent("""
            {title}

            {usage}

            The account is examined for URLS, a URL is chosen, and then that URL
            is opened in the chosen browser.  First URLS are gathered from the
            'urls' account attribute, which can be a string containing one or
            more URLS, a list, or a dictionary.  If 'urls' is a dictionary, the
            desired URL can be chosen by entering the key as an argument to the
            browse command. If a key is not given, then the 'default_url'
            account attribute is used to specify the key to use by default. If
            'urls' is not a dictionary, then the first URL specified is used.
            URLs are also taken from RecognizeURL objects in the 'discovery'
            account attribute.  If the 'name' argument is specified, the
            corresponding URL can be chosen using a key.

            The default browser is {default}. You can override the default
            browser on a per-account basis by adding an attribute named
            'browser' to the account.  An example of when you would specify the
            browser in an account would be an account associated with Tor hidden
            service, which generally can only be accessed using torbrowser:

                class SilkRoad(Account):
                    passcode = Passphrase()
                    username = Passphrase(length=2, sep='-')
                    url = 'http://silkroad6ownowfk.onion'
                    browser = 't'

            The available browsers are:
            {browsers}
        """).strip()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE,
            default=default_browser, browsers=browsers
        )

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # determine the account and open the URL
        account = generator.get_account(cmdline['<account>'])
        account.open_browser(
            cmdline['<key>'], cmdline['--browser'], cmdline['--list']
        )


# Changed {{{1
class Changed(Command):
    NAMES = 'changed', 'C'
    DESCRIPTION = 'show changes since archive was created'
    USAGE = dedent("""
        Usage:
            avendesora changed
            avendesora C

        When you run the 'archive' command it overwrites the existing
        archive. If you have accidentally deleted an account or changed a
        secret, then replacing the archive could cause the last copy of the
        original information to be lost. To prevent this from occurring it
        is a good practice to run the 'changed' command before regenerating
        the archive.  It describes all of the changes that have occurred
        since the last time the archive was generated. You should only
        regenerate the archive once you have convinced yourself all of the
        changes are as expected.
    """).strip()

    @classmethod
    def run(cls, command, args):
        # define white space insensitive compare function:
        def differ(a, b):
            a = ' '.join(repr(a).replace(r'\n', ' ').split())
            b = ' '.join(repr(b).replace(r'\n', ' ').split())
            return a != b

        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # read archive file
        archive_path = get_setting('archive_file')
        f = PythonFile(archive_path)
        archive = f.run()
        import arrow
        created = archive.get('CREATED')
        if created:
            created = arrow.get(created).format('YYYY-MM-DD hh:mm:ss A ZZ')
            output('archive created: %s' % created)
        archive_accounts = archive.get('ACCOUNTS')
        if not archive_accounts:
            raise PasswordError(
                'corrupt archive, ACCOUNTS missing.', culprit=archive_path
            )

        # run the generator
        generator = PasswordGenerator()

        # determine the account and open the URL
        current_accounts = {}
        for account in generator.all_accounts():
            entry = account.archive()
            if entry:
                current_accounts[account.get_name()] = entry

        # report any new or missing accounts
        new = set(current_accounts.keys()) - set(archive_accounts.keys())
        missing = set(archive_accounts.keys()) - set(current_accounts.keys())
        for each in sorted(new):
            output('new account:', each)
        for each in sorted(missing):
            output('missing account:', each)

        # for the common accounts, report any differences in the fields
        common = set(archive_accounts.keys()) & set(current_accounts.keys())
        for account_name in sorted(common):
            archive_account = archive_accounts[account_name]
            current_account = current_accounts[account_name]

            # report any new or missing fields
            new = set(current_account.keys()) - set(archive_account.keys())
            missing = set(archive_account.keys()) - set(current_account.keys())
            for each in sorted(new):
                output(account_name, 'new field', each, sep=': ')
            for each in sorted(missing):
                output(account_name, 'missing field', each, sep=': ')

            # for the common fields, report any differences in the values
            shared = set(archive_account.keys()) & set(current_account.keys())
            for field_name in sorted(shared):
                try:
                    archive_value = archive_account[field_name]
                    current_value = current_account[field_name]
                    if is_collection(current_value) != is_collection(archive_value):
                        output(account_name, 'field dimension differs', field_name, sep=': ')
                    elif is_collection(current_value):
                        archive_items = Collection(archive_account[field_name]).items()
                        current_items = Collection(current_account[field_name]).items()
                        archive_keys = set(k for k, v in archive_items)
                        current_keys = set(k for k, v in current_items)
                        new = current_keys - archive_keys
                        missing = archive_keys - current_keys
                        for each in sorted(new):
                            output(account_name, field_name, 'new member', each, sep=': ')
                        for each in sorted(missing):
                            output(account_name, field_name, 'missing member', each, sep=': ')
                        for k in sorted(archive_keys & current_keys):
                            if differ(archive_value[k], current_value[k]):
                                output(account_name, 'member differs', '%s[%s]' % (field_name, k), sep=': ')
                    else:
                        if differ(archive_value, current_value):
                            output(account_name, 'field differs', field_name, sep=': ')
                except Exception:
                    error(
                        'unanticipated situation.',
                        culprit=(account_name, field_name)
                    )
                    raise


# Conceal {{{1
class Conceal(Command):
    NAMES = 'conceal', 'c'
    DESCRIPTION = 'conceal text by encoding it'
    USAGE = dedent("""
        Usage:
            avendesora conceal [options] [<text>]
            avendesora c       [options] [<text>]

        Options:
            -e <encoding>, --encoding <encoding>
                                    Encoding used when concealing information.
            -g <id>, --gpg-id <id>  Use this ID when creating any missing encrypted files.
                                    Use commas with no spaces to separate multiple IDs.
            -h <path>, --gpg-home <path>
                                    GPG home directory (default is ~/.gnupg).
            -s, --symmetric         Encrypt with a passphrase rather than using your
                                    GPG key (only appropriate for gpg encodings).
    """).strip()

    @classmethod
    def help(cls):
        encodings = []
        for name, desc in ObscuredSecret.encodings():
            encodings.append('%s:\n%s' % (name, indent(desc, '    ')))
        encodings = '\n\n'.join(encodings)
        text = dedent("""
            {title}

            {usage}

            Possible encodings include{default_encoding}:

            {encodings}

            Though available as an option for convenience, you should not pass
            the text to be hidden as an argument as it is possible for others to
            examine the commands you run and their argument list. For any
            sensitive secret, you should simply run 'avendesora conceal' and
            then enter the secret text when prompted.
        """).strip()
        default_encoding = ObscuredSecret.default_encoding()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE, encodings=encodings,
            default_encoding=' (default encoding is %s)' % default_encoding,
        )

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # get the text
        encoding = cmdline['--encoding']
        text = cmdline['<text>']
        symmetric = cmdline['--symmetric']

        # get the gpg ids of those who will be able to decrypt the file
        gpg_ids = cmdline['--gpg-id']
        if gpg_ids:
            gpg_ids = gpg_ids.split(',')
        else:
            gpg_ids = get_setting('gpg_ids', [])

        if cmdline['--gpg-home']:
            override_setting('gpg_home', cmdline['--gpg-home'])

        if not text:
            output('Enter text to obscure, type ctrl-d to terminate.')
            text = sys.stdin.read()[:-1]

        # transform and output the string
        output(ObscuredSecret.hide(text, encoding, True, symmetric, gpg_ids))


# Edit {{{1
class Edit(Command):
    NAMES = 'edit', 'e'
    DESCRIPTION = 'edit an account'
    USAGE = dedent("""
        Usage:
            avendesora edit <account>
            avendesora e    <account>
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            Opens an existing account in your editor.

            You can specify the editor by changing the 'edit_account' setting in
            the config file (~/.config/avendesora/config).
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # determine the account file and back it up
        try:
            account = generator.get_account(cmdline['<account>'])
            accounts_file = PythonFile(account._file_info.path)
            accounts_file.backup('.saved')
            account_name = account.__name__
        except OSError as e:
            raise PasswordError(os_error(e))

        # allow the user to edit, and then check and make sure it is valid
        try:
            while True:
                GenericEditor.open(accounts_file.path, account_name)

                # check the changes to see if there are any issues
                try:
                    accounts_file.run()
                    break
                except PasswordError as e:
                    error(e)
                    if sys.version_info.major < 3:
                        response = raw_input('Try again? ')
                    else:
                        response = input('Try again? ')
                    if response.lower() not in ['y', 'yes']:
                        raise PasswordError(
                            'Giving up, restoring original version.'
                        )

        except PasswordError:
            accounts_file.restore()
            raise
        except OSError as e:
            accounts_file.restore()
            raise PasswordError(os_error(e))


# Find {{{1
class Find(Command):
    NAMES = 'find', 'f'
    DESCRIPTION = 'find an account'
    USAGE = dedent("""
        Find accounts whose name contains the search text.

        Usage:
            avendesora find <text>
            avendesora f    <text>
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # find accounts whose name matches the criteria
        to_print = []
        for acct in generator.find_accounts(cmdline['<text>']):
            aliases = Collection(getattr(acct, 'aliases', [])).values()

            aliases = ' (%s)' % (', '.join(aliases)) if aliases else ''
            to_print += [acct.get_name() + aliases]
        output(cmdline['<text>']+ ':')
        output('    ' + ('\n    '.join(sorted(to_print))))


# Help {{{1
class Help(Command):
    NAMES = 'help', 'h'
    DESCRIPTION = 'give information about commands or other topics'
    USAGE = dedent("""
        Usage:
            avendesora help [options] [<topic>]
            avendesora h    [options] [<topic>]

        Options:
            -s, --search            list topics that include <topic> as a search term.
            -b, --browse            open the topic in your default browser.
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # in this case we don't need to bother with a possibly encrypted logfile
        override_setting('discard_logfile', True)

        from .help import HelpMessage
        HelpMessage.show(cmdline['<topic>'], cmdline['--browse'], cmdline['--search'])


# Identity {{{1
class Identity(Command):
    NAMES = 'identity', 'ident', 'i'
    DESCRIPTION = 'generate an identifying response to a challenge'
    USAGE = dedent("""
        Usage:
            avendesora identity [<name> [<challenge>...]]
            avendesora ident    [<name> [<challenge>...]]
            avendesora i        [<name> [<challenge>...]]
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            This command allows you to generate a response to any challenge.
            The response identifies you to a partner with whom you have shared
            an account.

            If you run the command with no arguments, it prints the list of
            valid names. If you run it with no challenge, one is created for you
            based on the current time and date.

            If you have a remote partner to whom you wish to prove your
            identity, have that partner use avendesora to generate a challenge
            and a response based on your shared secret. Then the remote partner
            provides you with the challenge and you run avendesora with that
            challenge to generate the same response, which you provide to your
            remote partner to prove your identity.

            You are free to explicitly specify a challenge to start the process,
            but it is important that it be unpredictable and that you not use
            the same challenge twice. As such, it is recommended that you not
            provide the challenge. In this situation, one is generated for you
            based on the time and date.

            Consider an example that illustrates the process. In this example,
            Ahmed is confirming the identity of Reza, where both Ahmed and Reza
            are assumed to have shared Avendesora accounts.  Ahmed runs
            Avendesora as follows and remembers the response:

                > avendesora identity reza
                challenge: slouch emirate bedeck brooding
                response: spear disable local marigold

            This assumes that reza is the name, with any extension removed, of
            the file that Ahmed uses to contain their shared accounts.

            Ahmed communicates the challenge to Reza but not the response.  Reza
            then runs Avendesora with the given challenge:

                > avendesora identity ahmed slouch emirate bedeck brooding
                challenge: slouch emirate bedeck brooding
                response: spear disable local marigold

            In this example, ahmed is the name of the file that Reza uses to
            contain their shared accounts.

            To complete the process, Reza returns the response to Ahmed, who
            compares it to the response he received to confirm Reza's identity.
            If Ahmed has forgotten the desired response, he can also specify the
            challenge to the *identity* command to regenerate the expected
            response.
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        if cmdline['<name>']:
            try:
                name = cmdline['<name>']
                challenge = ' '.join(cmdline['<challenge>'])
                c, r = generator.challenge_response(name, challenge)
                output(c, culprit='challenge')
                output(r, culprit='response')
            except PasswordError as e:
                e.report()
        else:
            names = sorted(generator.shared_secrets.keys())
            output('Available names:')
            for name in names:
                output('  ', name)


# Initialize {{{1
class Initialize(Command):
    NAMES = 'initialize', 'init', 'I'
    DESCRIPTION = 'create initial set of Avendesora files'
    USAGE = dedent("""
        Usage:
            avendesora initialize [options]
            avendesora init       [options]
            avendesora I          [options]

        Options:
            -g <id>, --gpg-id <id>  Use this ID when creating any missing encrypted files.
                                    Use commas with no spaces to separate multiple IDs.
            -h <path>, --gpg-home <path>
                                    GPG home directory (default is ~/.gnupg).
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            Create Avendesora data directory (~/.config/avendesora) and populate
            it with initial versions of all essential files.

            It is safe to run this command even after the data directory and
            files have been created. Doing so will simply recreate any missing
            files.  Existing files are not modified.
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)
        if cmdline['--gpg-home']:
            override_setting('gpg_home', cmdline['--gpg-home'])

        # get the gpg ids of those who will be able to decrypt the file
        gpg_ids = cmdline['--gpg-id']
        if gpg_ids:
            gpg_ids = gpg_ids.split(',')
            # save the gpg_ids for the logfile in case it is encrypted.
            if not get_setting('gpg_ids'):
                override_setting('gpg_ids', gpg_ids)
        else:
            gpg_ids = get_setting('gpg_ids', [])

        # run the generator
        generator = PasswordGenerator(init=True, gpg_ids=gpg_ids)


# Log {{{1
class Log(Command):
    NAMES = 'log',
    DESCRIPTION = 'show the logfile'
    USAGE = dedent("""
        Usage:
            avendesora log
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            Opens the logfile in your editor.

            You can specify the editor by changing the 'edit_account' setting in
            the config file (~/.config/avendesora/config).
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # don't clobber the existing logfile
        override_setting('discard_logfile', True)

        # open the logfile
        logfile = get_setting('log_file')
        GenericEditor.open(logfile)


# Login Credentials {{{1
class LoginCredentials(Command):
    NAMES = 'credentials', 'login', 'l'
    DESCRIPTION = 'show login credentials'
    USAGE = dedent("""
        Displays the account's login credentials, which generally consist of an
        identifier and a secret.

        Usage:
            avendesora credentials [options] <account>
            avendesora login       [options] <account>
            avendesora l           [options] <account>

        Options:
            -S, --seed              Interactively request additional seed for
                                    generated secrets.
    """).strip()


    @classmethod
    def help(cls):
        idents=conjoin(get_setting('credential_ids').split(), conj=' or ')
        secrets=conjoin(get_setting('credential_secrets').split(), conj=' or ')
        text = dedent("""
            {title}

            {usage}

            The credentials can be specified explicitly using the credentials
            setting in your account. For example::

                credentials = 'usernames.0 usernames.1 passcode'

            If credentials is not specified then the first of the following will
            be used if available:

                id: {idents}
                secret: {secrets}

            If your credentials include more than one secret they will be
            presented one at a time for one minute each. You can cut the minute
            short by typing Ctrl-C.
        """).strip()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE,
            idents=idents, secrets=secrets,
        ).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # determine the account and output specified information
        account_name = cmdline['<account>']
        writer = get_writer(tty=True)
        account = generator.get_account(account_name, cmdline['--seed'])
        credentials = account.get_scalar('credentials', default=None)
        if credentials:
            credentials = credentials.split()
        else:
            ids = Collection(get_setting('credential_ids'))
            secrets = Collection(get_setting('credential_secrets'))
            for each in ids:
                if account.has_field(each):
                    identity = each
                    break
            else:
                identity = None
            for each in secrets:
                if account.has_field(each):
                    secret = each
                    break
            else:
                secret = None
            if not identity and not secret:
                raise PasswordError('credentials not found.')
            credentials = [identity, secret]
        for each in cull(credentials):
            writer.display_field(account, each)


# New {{{1
class New(Command):
    NAMES = 'new', 'N'
    DESCRIPTION = 'create new accounts file'
    USAGE = dedent("""
        Usage:
            avendesora new [options] <name>
            avendesora N   [options] <name>

        Options:
            -g <id>, --gpg-id <id>  Use this ID when creating any missing encrypted files.
                                    Use commas with no spaces to separate multiple IDs.
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            Creates a new accounts file. Accounts that share the same file share
            the same master seed by default and, if the file is encrypted,
            can be decrypted by the same recipients.

            Generally you create new accounts files for each person or group
            with which you wish to share accounts. You also use separate files
            for passwords with different security domains. For example, a
            high-value passwords might be placed in an encrypted file that would
            only be placed highly on protected computers. Conversely, low-value
            passwords might be contained in perhaps an unencrypted file that is
            found on many computers.

            Add a '.gpg' extension to <name> to encrypt the file.
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # get the gpg ids of those who will be able to decrypt the file
        gpg_ids = cmdline['--gpg-id']
        if gpg_ids:
            gpg_ids = gpg_ids.split(',')
        else:
            gpg_ids = get_setting('gpg_ids', [])

        # run the generator
        generator = PasswordGenerator(
            init=cmdline['<name>'], gpg_ids=sorted(gpg_ids)
        )


# Phonetic Alphabet {{{1
class PhoneticAlphabet(Command):
    NAMES = 'phonetic', 'alphabet', 'p'
    DESCRIPTION = 'display NATO phonetic alphabet'
    USAGE = dedent("""
        Usage:
            avendesora alphabet [<text>]
            avendesora phonetic [<text>]
            avendesora p [<text>]
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            If <text> is given, it is converted character by character to the
            phonetic alphabet. If not given, the entire phonetic alphabet is
            displayed.
        """).strip()
        return text.format(title=title(cls.DESCRIPTION), usage=cls.USAGE)

    @classmethod
    def run(cls, command, args):
        words = """
            Alfa Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo
            Lima Mike November Oscar Papa Quebec Romeo Sierra Tango Uniform
            Victor Whiskey X-ray Yankee Zulu
        """.split()
        mapping = {w[0].lower():w for w in words}
        mapping.update({
            '0':'Zero', '1':'One', '2':'Two', '3':'Three', '4':'Four',
            '5':'Five', '6':'Six', '7':'Seven', '8':'Eight', '9':'Nine'
        })

        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)
        arg = cmdline['<text>']

        if arg:
            converted = []
            for c in arg.lower():
                converted.append(mapping.get(c, c))
            output(' '.join(converted).lower())
        else:
            output('Phonetic alphabet:')
            output(columns(words))


# Reveal {{{1
class Reveal(Command):
    NAMES = 'reveal', 'r'
    DESCRIPTION = 'reveal concealed text'
    USAGE = dedent("""
        Transform concealed text to reveal its original form.

        Usage:
            avendesora reveal [<text>]
            avendesora r      [<text>]

        Options:
            -e <encoding>, --encoding <encoding>
                                    Encoding used when revealing information.
    """).strip()

    @classmethod
    def help(cls):
        text = dedent("""
            {title}

            {usage}

            Though available as an option for convenience, you should not pass
            the text to be revealed as an argument as it is possible for others
            to examine the commands you run and their argument list. For any
            sensitive secret, you should simply run 'avendesora reveal' and then
            enter the encoded text when prompted.
        """).strip()
        return text.format(
            title=title(cls.DESCRIPTION), usage=cls.USAGE
        )

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # get the text
        text = cmdline['<text>']
        if not text:
            output('Enter the obscured text, type ctrl-d to terminate.')
            text = sys.stdin.read()

        # transform and output the string
        output(ObscuredSecret.show(text))


# Search {{{1
class Search(Command):
    NAMES = 'search', 's'
    DESCRIPTION = 'search accounts'
    USAGE = dedent("""
        Search for accounts whose values contain the search text.

        Usage:
            avendesora search <text>
            avendesora s      <text>
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # search for accounts that match search criteria
        to_print = []
        for acct in generator.search_accounts(cmdline['<text>']):
            aliases = ', '.join(Collection(getattr(acct, 'aliases', [])).values())
            aliases = ' (%s)' % (aliases) if aliases else ''
            to_print += [acct.get_name() + aliases]
        output(cmdline['<text>'] + ':')
        output('    ' + ('\n    '.join(sorted(to_print))))


# Value {{{1
class Value(Command):
    NAMES = 'value', 'val', 'v'
    DESCRIPTION = 'show an account value'
    USAGE = dedent("""
        Produce an account value. If the value is secret, it is produced only
        temporarily unless --stdout is specified.

        Usage:
            avendesora value [options] [<account> [<field>]]
            avendesora val   [options] [<account> [<field>]]
            avendesora v     [options] [<account> [<field>]]
            avendesora vc    [options] [<account> [<field>]]

        Options:
            -c, --clipboard         Write output to clipboard rather than stdout.
            -s, --stdout            Write output to the standard output without
                                    any annotation or protections.
            -S, --seed              Interactively request additional seed for
                                    generated secrets.
            -v, --verbose           Add additional information to log file to
                                    help identify issues in account discovery.
            -T <title>, --title <title>
                                    Use account discovery on this title.

        The 'vc' command is a shortcut for 'value --clipboard'.

        You request a scalar value by specifying its name after the account.
        For example:

            avendesora value bank pin

        If the requested value is composite (an array or dictionary), you should
        also specify a key that indicates which of the composite values you
        want. For example, if the 'accounts' field is a dictionary, you specify
        accounts.checking or accounts[checking] to get information on your
        checking account. If the value is an array, you give the index of the
        desired value. For example, questions.0 or questions[0]. If you only
        specify a number, then the name is assumed to be 'questions', as in the
        list of security questions (this can be changed by specifying the
        desired name as the 'default_vector_field' in the account or the config
        file).

        The field may be also be a script, with is nothing but a string that it
        output as given except that embedded attributes are replaced by account
        field values. For example:

            avendesora value bank '{accounts.checking}: {passcode}'

        If no value is requested the result produced is determined by the value
        of the 'default' attribute (this can be changed by specifying
        'default_field' in the config file). If no value is given for 'default',
        then the *passcode*, *password*, or *passphrase* attribute is produced
        (this can be changed by specifying the 'default_field' in the account or
        the config file).  If 'default' is a script (see 'avendesora help
        scripts') then the script is executed. A typical script might be
        'username: {username}, password: {passcode}'. It is best if the script
        produces a one line output if it contains secrets. If not a script, the
        value of 'default' should be the name of another attribute, and the
        value of that attribute is shown.

        Normally the value command attempts to protects secrets. It does so
        clearing the screen after a minute. If multiple secrets are requested,
        you must either wait a minute to see each subsequent secret or type
        Ctrl-C to clear the current secret and move on.  If you use --clipboard,
        the clipboard is cleared after a minute.  However, if you use --stdout
        this clearing of the secret does not occur. The --stdout option is
        generally used with communicating with other Linux commands.  For
        example, you can send a passcode to the standard input of a command as
        follows:

            avendesora value --stdout gpg | gpg --passphrase-fd 0 ...

        You can place the username and password on a command line as follows:

            curl --user `avendesora value -s apache '{username}:{passcode}'` ...

        Be aware that it is possible for other users on shared Linux machines to
        see the command line arguments of your commands, so passing secrets as
        command arguments should only be used for low value secrets.

        If no account is requested, then Avendesora attempts to determine the
        appropriate account through discovery (see 'avendesora help discovery').
        Normally Avendesora is called in this manner from your window manager.
        You would arrange for it to be run when you type a hot key. In this case
        Avendesora determines which account to use from information available
        from the environment, information like the title on active window. In
        this mode, Avendesora mimics the keyboard when producing its output.

        The verbose and title options are used when debugging account
        discovery. The verbose option adds more information about the
        discovery process to the logfile (~/.config/avendesora/log.gpg). The
        title option allows you to override the active window title so you can
        debug title-based discovery. Specifying the title option also scrubs
        the output and outputs directly to the standard output rather than
        mimicking the keyboard so as to avoid exposing your secret.
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)
        use_clipboard = cmdline['--clipboard'] or cmdline['vc']

        # run the generator
        generator = PasswordGenerator()

        # determine the account and output specified information
        account_name = cmdline['<account>']
        if account_name:
            account = generator.get_account(account_name, cmdline['--seed'])
            writer = get_writer(
                clipboard=use_clipboard, stdout=cmdline['--stdout']
            )
            writer.display_field(account, cmdline['<field>'])
        else:
            # use discovery to determine account
            account_name, script = generator.discover_account(
                title=cmdline['--title'], verbose=cmdline['--verbose']
            )
            account = generator.get_account(account_name)
            writer = get_writer(tty=False)
            writer.run_script(account, script, cmdline['--title'])


# Values {{{1
class Values(Command):
    NAMES = 'values', 'vals', 'V'
    DESCRIPTION = 'display all account values'
    USAGE = dedent("""
        Show all account values.

        Usage:
            avendesora values <account>
            avendesora vals   <account>
            avendesora V      <account>
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # run the generator
        generator = PasswordGenerator()

        # determine the account
        account = generator.get_account(cmdline['<account>'])
        account.write_summary()


# Version {{{1
class Version(Command):
    NAMES = 'version',
    DESCRIPTION = 'display Avendesora version'
    USAGE = dedent("""
        Usage:
            avendesora version
    """).strip()

    @classmethod
    def run(cls, command, args):
        # read command line
        cmdline = docopt(cls.USAGE, argv=[command] + args)

        # get the Python version
        python = 'Python %s.%s.%s' % (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )

        # output the Avendesora version along with the Python version
        from .__init__ import __version__, __released__
        output('Avendesora version: %s (%s) [%s].' % (
            __version__, __released__, python
        ))
