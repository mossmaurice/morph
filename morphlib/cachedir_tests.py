# Copyright (C) 2011  Codethink Limited
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import unittest

import morphlib


class CacheDirTests(unittest.TestCase):

    def setUp(self):
        self.dirname = '/cache/dir'
        self.cachedir = morphlib.cachedir.CacheDir(self.dirname)

    def test_sets_dirname_attribute(self):
        self.assertEqual(self.cachedir.dirname, self.dirname)

