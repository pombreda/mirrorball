#
# Copyright (c) 2008-2009 rPath, Inc.
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

"""
Package source for APT repositories.
"""

import logging

import aptmd
from updatebot.pkgsource.common import BasePackageSource

log = logging.getLogger('updatebot.pkgsource')

class DebSource(BasePackageSource):
    """
    PackageSource backend for APT repositories.
    """

    def __init__(self, cfg):
        BasePackageSource.__init__(self, cfg)

        self._binPkgs = set()
        self._srcPkgs = set()

    def load(self):
        """
        Load repository metadata from a config object.
        """

        client = aptmd.Client(self._cfg.repositoryUrl)
        for repo in self._cfg.repositoryPaths:
            log.info('loading repository data %s' % repo)
            self.loadFromClient(client, repo)
            self._clients[repo] = client

        self.finalize()

    def loadFromClient(self, client, path):
        """
        Load repository metadata from a aptmd client object.
        """

        for pkg in client.parse(path):
            if pkg.arch in self._excludeArch:
                continue

            if pkg.arch == 'src':
                self._procSrc(pkg)
            else:
                self._procBin(pkg)

    def _procSrc(self, pkg):
        """
        Process source packages.
        """

        if pkg.name not in self.srcNameMap:
            self.srcNameMap[pkg.name] = set()
        self.srcNameMap[pkg.name].add(pkg)

        for location in pkg.files:
            self.locationMap[location] = pkg

        self._srcPkgs.add(pkg)

    def _procBin(self, pkg):
        """
        Process binary packages.
        """

        if pkg.name not in self.binNameMap:
            self.binNameMap[pkg.name] = set()
        self.binNameMap[pkg.name].add(pkg)

        self.locationMap[pkg.location] = pkg

        self._binPkgs.add(pkg)

    def finalize(self):
        """
        Finalize all data structures.
        """

        for srcPkg in self._srcPkgs:
            if srcPkg in self.srcPkgMap:
                continue

            self.srcPkgMap[srcPkg] = set()
            for binPkgName in srcPkg.binaries:
                if binPkgName not in self.binNameMap:
                    # This means that we don't have a binary package that was
                    # built with srcPkg, but that is ok.
                    continue

                for binPkg in self.binNameMap[binPkgName]:
                    if ((binPkg.version == srcPkg.version and
                         binPkg.release == srcPkg.release) or
                        (binPkg.source == srcPkg.name and
                         binPkg.sourceVersion == srcPkg.version)):
                        self.srcPkgMap[srcPkg].add(binPkg)

            self.srcPkgMap[srcPkg].add(srcPkg)

            for pkg in self.srcPkgMap[srcPkg]:
                self.binPkgMap[pkg] = srcPkg


        # It seems that some packages have versions that don't match up with
        # the source that they were built from. We need to handle that case.
        for binPkgs in self.binNameMap.itervalues():
            for binPkg in binPkgs:
                if binPkg not in self.binPkgMap:
                    pass
                    #log.warn('no source found for %s' % binPkg)
