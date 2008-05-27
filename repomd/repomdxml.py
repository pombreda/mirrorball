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

__all__ = ('RepoMdXml', )

# use stable api
from rpath_common.xmllib import api1 as xmllib

from primaryxml import PrimaryXml
from patchesxml import PatchesXml
from xmlcommon import XmlFileParser
from errors import UnknownElementError

class _RepoMd(xmllib.BaseNode):
    def addChild(self, child):
        if child.getName() == 'data':
            child.type = child.getAttribute('type')
            if child.type == 'patches':
                child._parser = PatchesXml(None, child.location)
                child.parseChildren = child._parser.parse
            elif child.type == 'primary':
                child._parser = PrimaryXml(None, child.location)
                child.parseChildren = child._parser.parse
            xmllib.BaseNode.addChild(self, child)
        else:
            raise UnknownElementError(child)

    def getRepoData(self, name=None):
        if not name:
            return self.getChildren('data')

        for node in self.getChildren('data'):
            if node.type == name:
                return node

        return None


class _RepoMdDataElement(xmllib.BaseNode):
    location = ''
    checksum = ''
    checksumType = 'sha'
    timestamp = ''
    openChecksum = ''
    openChecksumType = 'sha'

    def addChild(self, child):
        if child.getName() == 'location':
            self.location = child.getAttribute('href')
        elif child.getName() == 'checksum':
            self.checksum = child.finalize()
            self.checksumType = child.getAttribute('type')
        elif child.getName() == 'timestamp':
            self.timestamp = child.finalize()
        elif child.getName() == 'open-checksum':
            self.openChecksum = child.finalize()
            self.openChecksumType = child.getAttribute('type')
        else:
            raise UnknownElementError(child)


class RepoMdXml(XmlFileParser):
    def _registerTypes(self):
        self._databinder.registerType(_RepoMd, name='repomd')
        self._databinder.registerType(_RepoMdDataElement, name='data')
        self._databinder.registerType(xmllib.StringNode, name='checksum')
        self._databinder.registerType(xmllib.IntegerNode, name='timestamp')
        self._databinder.registerType(xmllib.StringNode, name='open-checksum')