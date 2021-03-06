#
# Copyright (c) SAS Institute, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


"""
Module for serializable representations of repository metadata.
"""

from xobj import xobj

import conary

class XDocManager(xobj.Document):
    """
    Base class that implements simple freeze/thaw methods.
    """

    data = str
    freeze = xobj.Document.toxml

    @classmethod
    def thaw(cls, xml):
        """
        Deserialize an xml string into a DocManager instance.
        """

        return xobj.parse(xml, documentClass=cls)

    @classmethod
    def fromfile(cls, fn):
        """
        Deserialize from file.
        """

        return xobj.parsef(fn, documentClass=cls)

    def tofile(self, fn):
        """
        Save model to file name.
        """

        fObj = open(fn, 'w')
        xml = self.toxml()
        fObj.write(xml)
        fObj.close()


class XDictItem(object):
    """
    Object to represent key/value pairs.
    """

    key = str
    value = str

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value

    def __hash__(self):
        return hash(self.key)

    def __cmp__(self, other):
        if type(other) in (str, unicode):
            return cmp(self.key, other)
        else:
            return cmp(self.key, other.key)


class XDict(object):
    """
    String based xobj dict implementation.
    """

    items = [ XDictItem ]

    def __init__(self):
        self.items = []
        self._itemClass = self.__class__.__dict__['items'][0]

    def __setitem__(self, key, value):
        item = self._itemClass(key, value)
        if item in self.items:
            idx = self.items.index(item)
            self.items[idx] = item
        else:
            self.items.append(item)

    def __getitem__(self, key):
        if key in self.items:
            idx = self.items.index(key)
            return self.items[idx].value
        raise KeyError, key

    def __contains__(self, key):
        return key in self.items


class XItemList(object):
    """
    List of items.
    """

    items = None

    def __init__(self):
        self.items = []
        self._itemClass = self.__class__.__dict__['items'][0]


class XHashableItem(object):
    """
    Base class for hashable items.
    """

    @property
    def key(self):
        raise NotImplementedError

    def __hash__(self):
        return hash(self.key)

    def __cmp__(self, other):
        return cmp(self.key, other.key)


class XPackageItem(XHashableItem):
    """
    Object to represent package data required for group builds with the
    managed group factory.
    """

    name = str
    version = str
    flavor = str
    byDefault = int
    use = str
    source = str

    def __init__(self, name=None, version=None, flavor=None, byDefault=None,
        use=None, source=None):

        self.name = name
        self.source = source

        if byDefault in (True, False):
            self.byDefault = int(byDefault)
        else:
            self.byDefault = byDefault

        if use in (True, False):
            self.use = int(use)
        else:
            self.use = use

        if isinstance(version, conary.versions.Version):
            self.version = version.freeze()
        else:
            self.version = version

        if isinstance(flavor, conary.deps.deps.Flavor):
            self.flavor = flavor.freeze()
        else:
            self.flavor = flavor

    @property
    def key(self):
        return (self.name, self.flavor, self.use)


class XPackageData(XItemList):
    """
    Mapping of package name to package group data.
    """

    items = [ XPackageItem ]


class XPackageDoc(XDocManager):
    """
    Document class for group data.
    """

    data = XPackageData


class XGroup(XHashableItem):
    """
    Group file info.
    """

    name = str
    filename = str
    byDefault = int
    depCheck = int
    checkPathConflicts = int

    def __init__(self, name=None, filename=None, byDefault=True, depCheck=True,
        checkPathConflicts=False):
        self.name = name
        self.filename = filename
        self.byDefault = byDefault and 1 or 0
        self.depCheck = depCheck and 1 or 0
        self.checkPathConflicts = checkPathConflicts and 1 or 0

    @property
    def key(self):
        return self.name


class XGroupList(XItemList):
    """
    List of file names to load as groups.
    """

    items = [ XGroup ]


class XGroupDoc(XDocManager):
    """
    Document for managing group.xml.
    """

    data = XGroupList
