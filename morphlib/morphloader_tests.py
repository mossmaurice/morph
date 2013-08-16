# Copyright (C) 2013  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import os
import shutil
import tempfile
import unittest

import morphlib


class MorphologyLoaderTests(unittest.TestCase):

    def setUp(self):
        self.loader = morphlib.morphloader.MorphologyLoader()
        self.tempdir = tempfile.mkdtemp()
        self.filename = os.path.join(self.tempdir, 'foo.morph')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_parses_yaml_from_string(self):
        string = '''\
name: foo
kind: chunk
build-system: dummy
'''
        morph = self.loader.parse_morphology_text(string, 'test')
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_fails_to_parse_utter_garbage(self):
        self.assertRaises(
            morphlib.morphloader.MorphologySyntaxError,
            self.loader.parse_morphology_text, ',,,', 'test')

    def test_fails_to_parse_non_dict(self):
        self.assertRaises(
            morphlib.morphloader.NotADictionaryError,
            self.loader.parse_morphology_text, '- item1\n- item2\n', 'test')

    def test_fails_to_validate_dict_without_kind(self):
        m = morphlib.morph3.Morphology({
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_chunk_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'chunk',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_chunk_with_invalid_field(self):
        m = morphlib.morph3.Morphology({
            'kind': 'chunk',
            'name': 'foo',
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_stratum_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'stratum',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_stratum_with_invalid_field(self):
        m = morphlib.morph3.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_system_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'system',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_system_with_invalid_field(self):
        m = morphlib.morph3.Morphology({
            'kind': 'system',
            'name': 'name',
            'arch': 'x86_64',
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_morphology_with_unknown_kind(self):
        m = morphlib.morph3.Morphology({
            'kind': 'invalid',
        })
        self.assertRaises(
            morphlib.morphloader.UnknownKindError, self.loader.validate, m)

    def test_validate_requires_unique_stratum_names_within_a_system(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "system",
                "name": "foo",
                "arch": "x86-64",
                "strata": [
                    {
                        "morph": "stratum",
                        "repo": "test1",
                        "ref": "ref"
                    },
                    {
                        "morph": "stratum",
                        "repo": "test2",
                        "ref": "ref"
                    }
                ]
            })
        self.assertRaises(ValueError, self.loader.validate, m)

    def test_validate_requires_unique_chunk_names_within_a_stratum(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "stratum",
                "name": "foo",
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "test1",
                        "ref": "ref"
                    },
                    {
                        "name": "chunk",
                        "repo": "test2",
                        "ref": "ref"
                    }
                ]
            })
        self.assertRaises(ValueError, self.loader.validate, m)

    def test_validate_requires_a_valid_architecture(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "system",
                "name": "foo",
                "arch": "blah",
                "strata": [],
            })
        self.assertRaises(
            morphlib.morphloader.UnknownArchitectureError,
            self.loader.validate, m)

    def test_validate_normalises_architecture_armv7_to_armv7l(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "system",
                "name": "foo",
                "arch": "armv7",
                "strata": [],
            })
        self.loader.validate(m)
        self.assertEqual(m['arch'], 'armv7l')

    def test_validate_requires_system_kind_to_be_tarball_if_present(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "system",
                "name": "foo",
                "arch": "armv7l",
                "strata": [],
                "system-kind": "blah",
            })

        self.assertRaises(
            morphlib.morphloader.InvalidSystemKindError,
            self.loader.validate, m)
        m['system-kind'] = 'rootfs-tarball'
        self.loader.validate(m)

    def test_validate_requires_build_deps_for_chunks_in_strata(self):
        m = morphlib.morph3.Morphology(
            {
                "kind": "stratum",
                "name": "foo",
                "chunks": [
                    {
                        "name": "foo",
                        "repo": "foo",
                        "ref": "foo",
                        "morph": "foo",
                        "build-mode": "bootstrap",
                    }
                ],
            })

        self.assertRaises(
            morphlib.morphloader.NoBuildDependenciesError,
            self.loader.validate, m)

    def test_validate_requires_build_deps_or_bootstrap_mode_for_strata(self):
        m = morphlib.morph3.Morphology(
            {
                "name": "stratum-no-bdeps-no-bootstrap",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "test:repo",
                        "ref": "sha1",
                        "build-depends": []
                    }
                ]
            })

        self.assertRaises(
            morphlib.morphloader.NoStratumBuildDependenciesError,
            self.loader.validate, m)

        m['build-depends'] = [
            {
                "repo": "foo",
                "ref": "foo",
                "morph": "foo",
            },
        ]
        self.loader.validate(m)

        del m['build-depends']
        m['chunks'][0]['build-mode'] = 'bootstrap'
        self.loader.validate(m)

    def test_validate_requires_chunks_in_strata(self):
        m = morphlib.morph3.Morphology(
            {
                "name": "stratum",
                "kind": "stratum",
                "chunks": [
                ],
                "build-depends": [
                    {
                        "repo": "foo",
                        "ref": "foo",
                        "morph": "foo",
                    },
                ],
            })

        self.assertRaises(
            morphlib.morphloader.EmptyStratumError,
            self.loader.validate, m)

    def test_loads_yaml_from_string(self):
        string = '''\
name: foo
kind: chunk
build-system: dummy
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_loads_json_from_string(self):
        string = '''\
{
    "name": "foo",
    "kind": "chunk",
    "build-system": "dummy"
}
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_loads_from_file(self):
        with open(self.filename, 'w') as f:
            f.write('''\
name: foo
kind: chunk
build-system: dummy
''')
        morph = self.loader.load_from_file(self.filename)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_saves_to_string(self):
        morph = morphlib.morph3.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'dummy',
        })
        text = self.loader.save_to_string(morph)

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
build-system: dummy
kind: chunk
name: foo
''')

    def test_saves_to_file(self):
        morph = morphlib.morph3.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'dummy',
        })
        self.loader.save_to_file(self.filename, morph)

        with open(self.filename) as f:
            text = f.read()

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
build-system: dummy
kind: chunk
name: foo
''')

    def test_validate_does_not_set_defaults(self):
        m = morphlib.morph3.Morphology({
            'kind': 'chunk',
            'name': 'foo',
        })
        self.loader.validate(m)
        self.assertEqual(sorted(m.keys()), sorted(['kind', 'name']))

    def test_sets_defaults_for_chunks(self):
        m = morphlib.morph3.Morphology({
            'kind': 'chunk',
            'name': 'foo',
        })
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'chunk',
                'name': 'foo',
                'description': '',
                'build-system': 'manual',

                'configure-commands': [],
                'pre-configure-commands': [],
                'post-configure-commands': [],

                'build-commands': [],
                'pre-build-commands': [],
                'post-build-commands': [],

                'test-commands': [],
                'pre-test-commands': [],
                'post-test-commands': [],

                'install-commands': [],
                'pre-install-commands': [],
                'post-install-commands': [],

                'chunks': [],
                'devices': [],
                'max-jobs': None,
            })

    def test_sets_defaults_for_strata(self):
        m = morphlib.morph3.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'chunks': [
                {
                    'name': 'bar',
                    'repo': 'bar',
                    'ref': 'bar',
                    'morph': 'bar',
                    'build-mode': 'bootstrap',
                    'build-depends': [],
                },
            ],
        })
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'stratum',
                'name': 'foo',
                'description': '',
                'build-depends': [],
                'chunks': [
                    {
                        'name': 'bar',
                        "repo": "bar",
                        "ref": "bar",
                        "morph": "bar",
                        'build-mode': 'bootstrap',
                        'build-depends': [],
                    },
                ],
            })

    def test_sets_defaults_for_system(self):
        m = morphlib.morph3.Morphology({
            'kind': 'system',
            'name': 'foo',
            'arch': 'x86_64',
        })
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'system',
                'system-kind': 'rootfs-tarball',
                'name': 'foo',
                'description': '',
                'arch': 'x86_64',
                'strata': [],
                'configuration-extensions': [],
                'disk-size': '1G',
            })

    def test_sets_stratum_chunks_repo_and_morph_from_name(self):
        m = morphlib.morph3.Morphology(
            {
                "name": "foo",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "le-chunk",
                        "ref": "ref",
                        "build-depends": [],
                    }
                ]
            })

        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['chunks'][0]['repo'], 'le-chunk')
        self.assertEqual(m['chunks'][0]['morph'], 'le-chunk')

    def test_convertes_max_jobs_to_an_integer(self):
        m = morphlib.morph3.Morphology(
            {
                "name": "foo",
                "kind": "chunk",
                "max-jobs": "42"
            })
        self.loader.set_defaults(m)
        self.assertEqual(m['max-jobs'], 42)

    def test_parses_simple_cluster_morph(self):
        string = '''
            name: foo
            kind: cluster
            systems:
                - morph: bar
        '''
        m = self.loader.parse_morphology_text(string, 'test')
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['name'], 'foo')
        self.assertEqual(m['kind'], 'cluster')
        self.assertEqual(m['systems'][0]['morph'], 'bar')
