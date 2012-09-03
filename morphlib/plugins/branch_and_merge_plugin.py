# Copyright (C) 2012  Codethink Limited
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


import cliapp
import copy
import os
import json
import glob
import tempfile
import urlparse

import morphlib


class BranchAndMergePlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('petrify', self.petrify,
                                arg_synopsis='STRATUM...')
        self.app.add_subcommand('init', self.init, arg_synopsis='[DIR]')
        self.app.add_subcommand('workspace', self.workspace,
                                arg_synopsis='')
        self.app.add_subcommand('branch', self.branch,
                                arg_synopsis='NEW [OLD]')
        self.app.add_subcommand('checkout', self.checkout,
                                arg_synopsis='BRANCH')
        self.app.add_subcommand('show-system-branch', self.show_system_branch,
                                arg_synopsis='')
        self.app.add_subcommand('show-branch-root', self.show_branch_root,
                                arg_synopsis='')
        self.app.add_subcommand('merge', self.merge,
                                arg_synopsis='BRANCH REPO...')
        self.app.add_subcommand('edit', self.edit,
                                arg_synopsis='REPO [REF]')

    def disable(self):
        pass

    @staticmethod
    def deduce_workspace():
        dirname = os.getcwd()
        while dirname != '/':
            dot_morph = os.path.join(dirname, '.morph')
            if os.path.isdir(dot_morph):
                return dirname
            dirname = os.path.dirname(dirname)
        raise cliapp.AppException("Can't find the workspace directory")

    @staticmethod
    def is_system_branch_directory(dirname):
        return os.path.isdir(os.path.join(dirname, '.morph-system-branch'))

    @classmethod
    def deduce_system_branch(cls):
        # 1. Deduce the workspace. If this fails, we're not inside a workspace.
        workspace = cls.deduce_workspace()

        # 2. We're in a workspace. Check if we're inside a system branch.
        #    If we are, return its name.
        dirname = os.getcwd()
        while dirname != workspace and dirname != '/':
            if cls.is_system_branch_directory(dirname):
                return os.path.relpath(dirname, workspace)
            dirname = os.path.dirname(dirname)

        # 3. We're in a workspace but not inside a branch. Try to find a
        #    branch directory in the directories below the current working
        #    directory. Avoid ambiguity by only recursing deeper if there
        #    is only one subdirectory.
        visited = set()
        for dirname, subdirs, files in os.walk(os.getcwd(), followlinks=True):
            # Avoid infinite recursion.
            if dirname in visited:
                subdirs[:] = []
                continue
            visited.add(dirname)

            if cls.is_system_branch_directory(dirname):
                return os.path.relpath(dirname, workspace)

            # Do not recurse deeper if we have more than one
            # non-hidden directory.
            subdirs[:] = [x for x in subdirs if not x.startswith('.')]
            if len(subdirs) > 1:
                break

        raise cliapp.AppException("Can't find the system branch directory")

    @staticmethod
    def write_branch_root(branch_dir, repo):
        filename = os.path.join(branch_dir, '.morph-system-branch',
                                'branch-root')
        with open(filename, 'w') as f:
            f.write('%s\n' % repo)

    def set_branch_config(self, branch_dir, option, value):
        filename = os.path.join(branch_dir, '.morph-system-branch', 'config')
        self.app.runcmd(['git', 'config', '-f', filename,
                         'branch.%s' % option, '%s' % value])

    def get_branch_config(self, branch_dir, option):
        filename = os.path.join(branch_dir, '.morph-system-branch', 'config')
        value = self.app.runcmd(['git', 'config', '-f', filename,
                                'branch.%s' % option])
        return value.strip()

    @staticmethod
    def clone_to_directory(app, dirname, reponame, ref):
        '''Clone a repository below a directory.

        As a side effect, clone it into the local repo cache.

        '''

        # Setup.
        cache = morphlib.util.new_repo_caches(app)[0]
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            app.settings['repo-alias'])

        # Get the repository into the cache; make sure it is up to date.
        repo = cache.cache_repo(reponame)
        if not app.settings['no-git-update']:
            repo.update()

        # Make sure the parent directories needed for the repo dir exist.
        parent_dir = os.path.dirname(dirname)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)

        # Clone it from cache to target directory.
        repo.checkout(ref, os.path.abspath(dirname))

        # Remember the repo name we cloned from in order to be able
        # to identify the repo again later using the same name, even
        # if the user happens to rename the directory.
        app.runcmd(['git', 'config', 'morph.repository', reponame],
                   cwd=dirname)

        # Set the origin to point at the original repository.
        morphlib.git.set_remote(app.runcmd, dirname, 'origin', repo.url)

        # Add push url rewrite rule to .git/config.
        app.runcmd(['git', 'config',
                    ('url.%s.pushInsteadOf' %
                     resolver.push_url(reponame)),
                    resolver.pull_url(reponame)], cwd=dirname)

        app.runcmd(['git', 'remote', 'update'], cwd=dirname)

    @staticmethod
    def resolve_reponame(app, reponame):
        '''Return the full pull URL of a reponame.'''

        resolver = morphlib.repoaliasresolver.RepoAliasResolver(
            app.settings['repo-alias'])
        return resolver.pull_url(reponame)

    @staticmethod
    def load_morphologies(dirname):
        pattern = os.path.join(dirname, '*.morph')
        for filename in glob.iglob(pattern):
            with open(filename) as f:
                text = f.read()
            morphology = morphlib.morph2.Morphology(text)
            yield filename, morphology

    @classmethod
    def morphs_for_repo(cls, app, morphs_dirname, repo):
        for filename, morph in cls.load_morphologies(morphs_dirname):
            if morph['kind'] == 'stratum':
                for spec in morph['chunks']:
                    spec_repo = cls.resolve_reponame(app, spec['repo'])
                    if spec_repo == repo:
                        yield filename, morph
                        break

    @classmethod
    def find_edit_ref(cls, app, morphs_dirname, repo):
        for filename, morph in cls.morphs_for_repo(app, morphs_dirname, repo):
            for spec in morph['chunks']:
                spec_repo = cls.resolve_reponame(app, spec['repo'])
                if spec_repo == repo:
                    return spec['ref']
        return None

    @staticmethod
    def write_morphology(filename, morphology):
        as_dict = {}
        for key in morphology.keys():
            value = morphology[key]
            if value:
                as_dict[key] = value
        with morphlib.savefile.SaveFile(filename, 'w') as f:
            json.dump(as_dict, fp=f, indent=4, sort_keys=True)
            f.write('\n')

    def petrify(self, args):
        '''Make refs to chunks be absolute SHA-1s.'''

        app = self.app
        cache = morphlib.util.new_repo_caches(app)[0]

        for filename in args:
            with open(filename) as f:
                morph = morphlib.morph2.Morphology(f.read())

            if morph['kind'] != 'stratum':
                app.status(msg='Not a stratum: %(filename)s',
                           filename=filename)
                continue

            app.status(msg='Petrifying %(filename)s', filename=filename)

            for source in morph['chunks']:
                reponame = source.get('repo', source['name'])
                ref = source['ref']
                app.status(msg='Looking up sha1 for %(repo_name)s %(ref)s',
                           repo_name=reponame,
                           ref=ref)
                assert cache.has_repo(reponame)
                repo = cache.get_repo(reponame)
                source['ref'] = repo.resolve_ref(ref)

            self.write_morphology(filename, morph)

    def init(self, args):
        '''Initialize a workspace directory.'''

        if not args:
            args = ['.']
        elif len(args) > 1:
            raise cliapp.AppException('init must get at most one argument')

        dirname = args[0]

        # verify the workspace is empty (and thus, can be used) or
        # create it if it doesn't exist yet
        if os.path.exists(dirname):
            if os.listdir(dirname) != []:
                raise cliapp.AppException('can only initialize empty '
                                          'directory as a workspace: %s' %
                                          dirname)
        else:
            try:
                os.makedirs(dirname)
            except:
                raise cliapp.AppException('failed to create workspace: %s' %
                                          dirname)

        os.mkdir(os.path.join(dirname, '.morph'))
        self.app.status(msg='Initialized morph workspace', chatty=True)

    def workspace(self, args):
        '''Find morph workspace directory from current working directory.'''

        self.app.output.write('%s\n' % self.deduce_workspace())

    def branch(self, args):
        '''Branch the whole system.'''

        if len(args) not in [2, 3]:
            raise cliapp.AppException('morph branch needs name of branch '
                                      'as parameter')

        repo = args[0]
        new_branch = args[1]
        commit = 'master' if len(args) == 2 else args[2]

        # Create the system branch directory.
        workspace = self.deduce_workspace()
        branch_dir = os.path.join(workspace, new_branch)
        os.makedirs(branch_dir)

        # Create a .morph-system-branch directory to clearly identify
        # this directory as a morph system branch.
        os.mkdir(os.path.join(branch_dir, '.morph-system-branch'))

        # Remember the repository we branched off from.
        self.set_branch_config(branch_dir, 'branch-root', repo)

        # Clone into system branch directory.
        repo_dir = os.path.join(branch_dir, self.convert_uri_to_path(repo))
        self.clone_to_directory(self.app, repo_dir, repo, commit)

        # Create a new branch in the local morphs repository.
        self.app.runcmd(['git', 'checkout', '-b', new_branch, commit],
                        cwd=repo_dir)

    def convert_uri_to_path(self, uri):
        parts = urlparse.urlparse(uri)

        # If the URI path is relative, assume it is an aliased repo (e.g.
        # baserock:morphs). Otherwise assume it is a full URI where we need
        # to strip off the scheme and .git suffix.
        if not os.path.isabs(parts.path):
            return uri
        else:
            path = parts.netloc
            if parts.path.endswith('.git'):
                path = os.path.join(path, parts.path[1:-len('.git')])
            else:
                path = os.path.join(path, parts.path[1:])
            return path

    def find_repository(self, branch_dir, repo):
        visited = set()
        for dirname, subdirs, files in os.walk(branch_dir, followlinks=True):
            # Avoid infinite recursion.
            if dirname in visited:
                subdirs[:] = []
                continue
            visited.add(dirname)

            # Check if the current directory is a git repository and, if so,
            # whether it was cloned from the repo we are looking for.
            if '.git' in subdirs:
                try:
                    original_repo = self.app.runcmd(
                        ['git', 'config', 'morph.repository'], cwd=dirname)
                    original_repo = original_repo.strip()

                    if repo == original_repo:
                        return dirname
                except:
                    pass

            # Do not recurse into hidden directories.
            subdirs[:] = [x for x in subdirs if not x.startswith('.')]

    def checkout(self, args):
        '''Check out an existing system branch.'''

        if len(args) != 2:
            raise cliapp.AppException('morph checkout needs a repo and the '
                                      'name of a branch as parameters')

        repo = args[0]
        system_branch = args[1]

        # Create the system branch directory.
        workspace = self.deduce_workspace()
        branch_dir = os.path.join(workspace, system_branch)
        os.makedirs(branch_dir)

        # Create a .morph-system-branch directory to clearly identify
        # this directory as a morph system branch.
        os.mkdir(os.path.join(branch_dir, '.morph-system-branch'))

        # Remember the repository we branched off from.
        self.set_branch_config(branch_dir, 'branch-root', repo)

        # Clone into system branch directory.
        repo_dir = os.path.join(branch_dir, self.convert_uri_to_path(repo))
        self.clone_to_directory(self.app, repo_dir, repo, system_branch)

    def show_system_branch(self, args):
        '''Print name of current system branch.'''

        self.app.output.write('%s\n' % self.deduce_system_branch())

    def show_branch_root(self, args):
        '''Print name of the repository that was branched off from.'''

        workspace = self.deduce_workspace()
        system_branch = self.deduce_system_branch()
        branch_dir = os.path.join(workspace, system_branch)
        branch_root = self.get_branch_config(branch_dir, 'branch-root')
        self.app.output.write('%s\n' % branch_root)

    def merge(self, args):
        '''Merge specified repositories from another system branch.'''

        if len(args) < 2:
            raise cliapp.AppException('morph merge must get a branch name '
                                      'and some repo names as arguments')

        other_branch = args[0]
        workspace = self.deduce_workspace()
        this_branch = self.deduce_system_branch()

        for repo in args[1:]:
            repo_url = self.resolve_reponame(self.app, repo)
            repo_path = self.convert_uri_to_path(repo)
            pull_from = urlparse.urljoin(
                'file://', os.path.join(workspace, other_branch, repo_path))
            repo_dir = os.path.join(workspace, this_branch, repo_path)
            self.app.runcmd(['git', 'pull', pull_from, other_branch],
                            cwd=repo_dir)

    def edit(self, args):
        '''Edit a component in a system branch.'''

        if len(args) not in (1, 2):
            raise cliapp.AppException('morph edit must get a repository name '
                                      'and commit ref as argument')

        workspace = self.deduce_workspace()
        system_branch = self.deduce_system_branch()

        # Find out which repository we branched off from.
        branch_dir = os.path.join(workspace, system_branch)
        branch_root = self.get_branch_config(branch_dir, 'branch-root')
        branch_root_dir = self.find_repository(branch_dir, branch_root)

        # Find out which repository to edit.
        repo, repo_url = args[0], self.resolve_reponame(self.app, args[0])

        # Find out which ref of the edit repo to check out.
        if len(args) == 2:
            ref = args[1]
        else:
            ref = self.find_edit_ref(self.app, branch_root_dir, repo_url)
            if ref is None:
                raise morphlib.Error('Cannot deduce commit to start edit from')

        # Clone the repository to be edited.
        repo_dir = os.path.join(branch_dir, self.convert_uri_to_path(repo))
        self.clone_to_directory(self.app, repo_dir, repo, ref)

        if system_branch == ref:
            self.app.runcmd(['git', 'checkout', system_branch],
                            cwd=repo_dir)
        else:
            self.app.runcmd(['git', 'checkout', '-b', system_branch, ref],
                            cwd=repo_dir)

        for filename, morph in \
                self.morphs_for_repo(self.app, branch_root_dir, repo_url):
            changed = False
            for spec in morph['chunks']:
                spec_repo = self.resolve_reponame(self.app, spec['repo'])
                if spec_repo == repo_url and spec['ref'] != system_branch:
                    self.app.status(msg='Replacing ref "%(ref)s" with '
                                    '"%(branch)s" in %(filename)s',
                                    ref=spec['ref'], branch=system_branch,
                                    filename=filename, chatty=True)
                    spec['ref'] = system_branch
                    changed = True
            if changed:
                self.write_morphology(filename, morph)