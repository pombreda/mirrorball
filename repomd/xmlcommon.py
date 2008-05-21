#
# Copyright (c) 2008 rPath, Inc.
#
# This program is distributed under the terms of the Common Public License,
# version 1.0. A copy of this license should have been distributed with this
# source file in a file called LICENSE. If it is not present, the license
# is always available at http://www.rpath.com/permanent/licenses/CPL-1.0.
#
# This program is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the Common Public License for
# full details.
#

__all__ = ('XmlFileParser', )

from rpath_common.xmllib import api1 as xmllib

class XmlFileParser(object):
    def __init__(self, repository, path):
        self._repository = repository
        self._path = path

        self._databinder = xmllib.DataBinder()
        self._registerTypes()

        self._data = None

    def _registerTypes(self):
        pass

    def parse(self, refresh=False):
        if not self._data or refresh:
            fn = self._repository.get(self._path)
            self._data = self._databinder.parseFile(fn)

            for child in self._data.iterChildren():
                if hasattr(child, '_parser'):
                    child._parser._repository = self._repository

        return self._data
