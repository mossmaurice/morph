# Copyright (C) 2011-2012  Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import binascii
import cliapp
import ConfigParser
import logging
import os
import re
import StringIO

import cliapp

import morphlib


class NoModulesFileError(cliapp.AppException):

    def __init__(self, repo, ref):
        Exception.__init__(self,
                           '%s:%s has no .gitmodules file.' % (repo, ref))


class Submodule(object):

    def __init__(self, name, url, path):
        self.name = name
        self.url = url
        self.path = path


class InvalidSectionError(cliapp.AppException):

    def __init__(self, repo, ref, section):
        Exception.__init__(self,
                           '%s:%s:.gitmodules: Found a misformatted section '
                           'title: [%s]' % (repo, ref, section))


class MissingSubmoduleCommitError(cliapp.AppException):

    def __init__(self, repo, ref, submodule):
        Exception.__init__(self,
                           '%s:%s:.gitmodules: No commit object found for '
                           'submodule "%s"' % (repo, ref, submodule))


class Submodules(object):

    def __init__(self, app, repo, ref):
        self.app = app
        self.repo = repo
        self.ref = ref
        self.submodules = []

    def load(self):
        content = self._read_gitmodules_file()

        io = StringIO.StringIO(content)
        parser = ConfigParser.RawConfigParser()
        parser.readfp(io)

        self._validate_and_read_entries(parser)

    def _read_gitmodules_file(self):
        try:
            # try to read the .gitmodules file from the repo/ref
            content = self.app.runcmd(
                ['git', 'cat-file', 'blob', '%s:.gitmodules' % self.ref],
                cwd=self.repo)

            # drop indentation in sections, as RawConfigParser cannot handle it
            return '\n'.join([line.strip() for line in content.splitlines()])
        except cliapp.AppException:
            raise NoModulesFileError(self.repo, self.ref)

    def _validate_and_read_entries(self, parser):
        for section in parser.sections():
            # validate section name against the 'section "foo"' pattern
            section_pattern = r'submodule "(.*)"'
            if re.match(section_pattern, section):
                # parse the submodule name, URL and path
                name = re.sub(section_pattern, r'\1', section)
                url = parser.get(section, 'url')
                path = parser.get(section, 'path')

                # create a submodule object
                submodule = Submodule(name, url, path)
                try:
                    # list objects in the parent repo tree to find the commit
                    # object that corresponds to the submodule
                    commit = self.app.runcmd(['git', 'ls-tree', self.ref,
                                              submodule.name], cwd=self.repo)

                    # read the commit hash from the output
                    fields = commit.split()
                    if len(fields) >= 2 and fields[1] == 'commit':
                        submodule.commit = commit.split()[2]

                        # fail if the commit hash is invalid
                        if len(submodule.commit) != 40:
                            raise MissingSubmoduleCommitError(self.repo,
                                                              self.ref,
                                                              submodule.name)

                        # add a submodule object to the list
                        self.submodules.append(submodule)
                    else:
                        logging.warning('Skipping submodule "%s" as %s:%s has '
                                        'a non-commit object for it' %
                                        (submodule.name, self.repo, self.ref))
                except cliapp.AppException:
                    raise MissingSubmoduleCommitError(self.repo, self.ref,
                                                      submodule.name)
            else:
                raise InvalidSectionError(self.repo, self.ref, section)

    def __iter__(self):
        for submodule in self.submodules:
            yield submodule

    def __len__(self):
        return len(self.submodules)

def get_user_name(runcmd):
    '''Get user.name configuration setting. Complain if none was found.'''
    if 'GIT_AUTHOR_NAME' in os.environ:
        return os.environ['GIT_AUTHOR_NAME'].strip()
    try:
        return runcmd(['git', 'config', 'user.name']).strip()
    except cliapp.AppException:
        raise cliapp.AppException(
            'No git user info found. Please set your identity, using: \n'
            '    git config --global user.name "My Name"\n'
            '    git config --global user.email "me@example.com"\n')


def set_remote(runcmd, gitdir, name, url):
    '''Set remote with name 'name' use a given url at gitdir'''
    return runcmd(['git', 'remote', 'set-url', name, url], cwd=gitdir)


def copy_repository(runcmd, repo, destdir):
    '''Copies a cached repository into a directory using cp.

    This also fixes up the repository afterwards, so that it can contain
    code etc.  It does not leave any given branch ready for use.

    '''
    runcmd(['cp', '-a', repo, os.path.join(destdir, '.git')])
    # core.bare should be false so that git believes work trees are possible
    runcmd(['git', 'config', 'core.bare', 'false'], cwd=destdir)
    # we do not want the origin remote to behave as a mirror for pulls
    runcmd(['git', 'config', '--unset', 'remote.origin.mirror'], cwd=destdir)
    # we want a traditional refs/heads -> refs/remotes/origin ref mapping
    runcmd(['git', 'config', 'remote.origin.fetch',
            '+refs/heads/*:refs/remotes/origin/*'], cwd=destdir)
    # set the origin url to the cached repo so that we can quickly clean up
    runcmd(['git', 'config', 'remote.origin.url', repo], cwd=destdir)
    # by packing the refs, we can then edit then en-masse easily
    runcmd(['git', 'pack-refs', '--all', '--prune'], cwd=destdir)
    # turn refs/heads/* into refs/remotes/origin/* in the packed refs
    # so that the new copy behaves more like a traditional clone.
    logging.debug("Adjusting packed refs for %s" % destdir)
    with open(os.path.join(destdir, ".git", "packed-refs"), "r") as ref_fh:
        pack_lines = ref_fh.read().split("\n")
    with open(os.path.join(destdir, ".git", "packed-refs"), "w") as ref_fh:
        ref_fh.write(pack_lines.pop(0) + "\n")
        for refline in pack_lines:
            if ' refs/remotes/' in refline:
                continue
            if ' refs/heads/' in refline:
                sha, ref = refline[:40], refline[41:]
                if ref.startswith("refs/heads/"):
                    ref = "refs/remotes/origin/" + ref[11:]
                refline = "%s %s" % (sha, ref)
            ref_fh.write("%s\n" % (refline))
    # Finally run a remote update to clear up the refs ready for use.
    runcmd(['git', 'remote', 'update', 'origin', '--prune'], cwd=destdir)


def checkout_ref(runcmd, gitdir, ref):
    '''Checks out a specific ref/SHA1 in a git working tree.'''
    runcmd(['git', 'checkout', ref], cwd=gitdir)


def index_has_changes(runcmd, gitdir):
    '''Returns True if there are no staged changes to commit'''
    try:
        runcmd(['git', 'diff-index', '--cached', '--quiet',
                '--ignore-submodules', 'HEAD'], cwd=gitdir)
    except cliapp.AppException:
        return True
    return False


def reset_workdir(runcmd, gitdir):
    '''Removes any differences between the current commit '''
    '''and the status of the working directory'''
    runcmd(['git', 'clean', '-fxd'], cwd=gitdir)
    runcmd(['git', 'reset', '--hard', 'HEAD'], cwd=gitdir)


def clone_into(runcmd, srcpath, targetpath, ref=None):
    '''Clones a repo in srcpath into targetpath, optionally directly at ref.'''
    if ref is None:
        runcmd(['git', 'clone', srcpath, targetpath])
    else:
        runcmd(['git', 'clone', '-b', ref, srcpath, targetpath])

def find_first_ref(runcmd, gitdir, ref):
    '''Find the *first* ref match and returns its sha1.'''
    return runcmd(['git', 'show-ref', ref],
                  cwd=gitdir).split("\n")[0].split(" ")[0]
