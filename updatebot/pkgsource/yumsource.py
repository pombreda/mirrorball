#
# Copyright (c) 2006,2008-2010 rPath, Inc.
#
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
Module for interacting with packages in multiple yum repositories.
"""

import os
import itertools
import logging

import repomd
from updatebot.lib import util
from updatebot.pkgsource.common import BasePackageSource

from updatebot.errors import CanNotFindSourceForBinariesError

log = logging.getLogger('updatebot.pkgsource')

def loaded(func):
    def wrapper(self, *args, **kwargs):
        if self._loaded:
            return
        return func(self, *args, **kwargs)
    return wrapper


class YumSource(BasePackageSource):
    """
    Class that builds maps of packages from multiple yum repositories.
    """

    PkgClass = repomd.packagexml._Package

    def __init__(self, cfg):
        BasePackageSource.__init__(self, cfg)

        # {srcTup: srpm}
        self._srcMap = dict()

        # {srcTup: {rpm: path}
        self._rpmMap = dict()

        # set of all src pkg objects
        self._srcPkgs = set()

        # mapping of what arch repository each binary package came from
        # {binPkg: set([archStr, ..])}
        self._repoMap = dict()

    def setLoaded(self):
        self._loaded = True

    @loaded
    def load(self):
        """
        Load package source based on config data.
        """

        for repo in self._cfg.repositoryPaths:
            log.info('loading repository data %s' % repo)
            client = repomd.Client(self._cfg.repositoryUrl + '/' + repo)
            archStr = self._cfg.repositoryArch.get(repo, None)
            self.loadFromClient(client, repo, archStr=archStr)
            self._clients[repo] = client

        self.finalize()
        self._loaded = True

    @loaded
    def loadFromUrl(self, url, basePath='', archStr=None):
        """
        Walk the yum repository rooted at url/basePath and collect information
        about rpms found.
        @param url: url to common directory on host where all repositories resides.
        @type url: string
        @param basePath: directory where repository resides.
        @type basePath: string
        """

        log.info('loading repository data %s/%s' % (url, basePath))
        client = repomd.Client(url + '/' + basePath)
        self.loadFromClient(client, basePath=basePath, archStr=archStr)

    @loaded
    def loadFromClient(self, client, basePath='', archStr=None):
        """
        Walk the yum repository rooted at url/basePath and collect information
        about rpms found.
        @param client: client object for extracting data from the repo metadata
        @type client: repomd.Client
        @param basePath: path to prefix location metadata with
        @type basePath: string
        """

        for pkg in client.getPackageDetail():
            # ignore the 32-bit compatibility libs - we will
            # simply use the 32-bit components from the repository
            if self._cfg.ignore32bitPackages and '32bit' in pkg.name:
                continue

            # Don't use all arches.
            if pkg.arch in self._excludeArch:
                continue

            assert '-' not in pkg.version
            assert '-' not in pkg.release

            pkg.location = basePath + '/' + pkg.location

            if self._excludeLocation(pkg.location):
                continue

            # ignore 32bit rpms in a 64bit repo.
            if (pkg.arch in ('i386', 'i586', 'i686') and
                'x86_64' in pkg.location):
                continue

            # Source RPM is one without a "sourcerpm" element
            if pkg.sourcerpm == '' or pkg.sourcerpm is None:
                self._procSrc(pkg)
            else:
                self._procBin(pkg, archStr=archStr)

    def _procSrc(self, package):
        """
        Process source rpms.
        @param package: package object
        @type package: repomd.packagexml._Package
        """

        other = package
        if package in self._srcPkgs:
            other = [ x for x in self._srcPkgs if x == package ][0]
            self.srcNameMap[package.name].remove(other)
            self._srcPkgs.remove(other)
            if package.getFileName() == os.path.basename(package.location):
                other = package

        self.srcNameMap.setdefault(package.name, set()).add(other)
        self.locationMap[package.location] = package

        # In case the a synthesized source ever turns into real source add the
        # short name for backward compatibility.
        if self._cfg.synthesizeSources:
            baseLoc = os.path.basename(package.location)
            if baseLoc not in self.locationMap:
                self.locationMap[baseLoc] = package

        self._srcPkgs.add(other)
        self._srcMap[(package.name, package.epoch, package.version,
                      package.release, package.arch)] = package

    def _procBin(self, package, archStr=None):
        """
        Process binary rpms.
        @param package: package object
        @type package: repomd.packagexml._Package
        """

        # FIXME: There should be a better way to figure out the tuple that
        #        represents the hash of the srcPkg.
        srcParts = package.sourcerpm.split('-')
        srcName = '-'.join(srcParts[:-2])
        srcVersion = srcParts[-2]
        if srcParts[-1].endswith('.src.rpm'):
            srcRelease = srcParts[-1][:-8] # remove '.src.rpm'
        elif srcParts[-1].endswith('.nosrc.rpm'):
            srcRelease = srcParts[-1][:-10]

        rpmMapKey = (srcName, package.epoch, srcVersion, srcRelease, 'src')
        self._rpmMap.setdefault(rpmMapKey, set()).add(package)

        # The normal case of "obsoletes foo < version" (or with
        # "requires foo", though that normally also follows the
        # "< version" pattern) is "keep in sync", which we do
        # already through groups.
        # The point of explicit obsoletes handling is what redirects
        # are used for in native conary packages, not for what groups
        # are used for.
        obsoleteNames = set(
                x.name for x in itertools.chain(*[
                    y.getChildren('rpm:entry') for y in package.format
                    if isinstance(y, repomd.packagexml._RpmObsoletes)])
                if not x.version)
        if obsoleteNames:
            requiresNames = set(
                    x.name for x in itertools.chain(*[
                        y.getChildren('rpm:entry') for y in package.format
                        if isinstance(y, repomd.packagexml._RpmRequires)]))
            obsoleteNames -= requiresNames
            if obsoleteNames:
                self.obsoletesMap[package] = obsoleteNames

        if package.name not in self.binNameMap:
            self.binNameMap[package.name] = set()
        self.binNameMap[package.name].add(package)

        self.locationMap[package.location] = package

        if archStr:
            self._repoMap.setdefault(package, set()).add(archStr)

    def _excludeLocation(self, location):
        """
        Method for filtering packages based on location.
        """

        return False

    @loaded
    def finalize(self):
        """
        Make some final datastructures now that we are done populating object.
        """

        # Build source structures from binaries if no sources are available from
        # the repository.
        if self._cfg.synthesizeSources:
            self._createSrcMap()

        # Now that we have processed all of the rpms, build some more data
        # structures.
        count = 0
        toDelete = set()
        srcToDelete = set()
        for pkg in self._srcPkgs:
            key = (pkg.name, pkg.epoch, pkg.version, pkg.release, pkg.arch)
            if pkg in self.srcPkgMap:
                continue

            if key not in self._rpmMap:
                log.warn('found source without binary rpms: %s' % pkg)
                #log.debug(key)
                #log.debug([ x for x in self._rpmMap if x[0] == key[0] ])

                count += 1
                if pkg in self.srcNameMap[pkg.name]:
                    self.srcNameMap[pkg.name].remove(pkg)
                srcToDelete.add(pkg)
                continue

            self.srcPkgMap[pkg] = self._rpmMap[key]
            self.srcPkgMap[pkg].add(pkg)

            # Remove any duplicate sources, favoring sources with the source
            # version in the file name.
            # FIXME: This doesn't really work for nosrc rpms
            sources = sorted([ (os.path.basename(x.location), x)
                for x in self.srcPkgMap[pkg] if x.arch in ('src', 'nosrc') ])
            if len(sources) > 1:
                primary = None
                for fn, src in sources:
                    if fn == '%s-%s-%s.%s.rpm' % (src.name, src.version, src.release, src.arch):
                        primary = src
                        break

                if primary:
                    for fn, src in sources:
                        if src is not primary:
                            self.srcPkgMap[pkg].remove(src)

            toDelete.add(key)

            for binPkg in self.srcPkgMap[pkg]:
                self.binPkgMap[binPkg] = pkg

        if count > 0:
            log.warn('found %s source rpms without matching binary '
                     'rpms' % count)

        # Remove references to sources that don't match binaries
        for pkg in srcToDelete:
            self._srcPkgs.remove(pkg)

        # Defer deletes, contents of rpmMap are used more than once.
        for key in toDelete:
            del self._rpmMap[key]

        # Attempt to match up remaining binaries with srpms.
        for srcTup in self._rpmMap.keys():
            srcKey = list(srcTup)
            epoch = int(srcKey[1])
            while epoch >= 0:
                srcKey[1] = str(epoch)
                key = tuple(srcKey)
                if key in self._srcMap:
                    srcPkg = self._srcMap[key]
                    for binPkg in self._rpmMap[srcTup]:
                        self.srcPkgMap[srcPkg].add(binPkg)
                        self.binPkgMap[binPkg] = srcPkg
                    del self._rpmMap[srcTup]
                    break
                epoch -= 1

        if self._rpmMap:
            count = sum([ len(x) for x in self._rpmMap.itervalues() ])
            log.warn('found %s binary rpms without matching srpms' % count)

            srcs = {}
            for x in self._rpmMap.itervalues():
                for y in x:
                    # skip debuginfo rpms
                    if 'debuginfo' in y.location or 'debugsource' in y.location:
                        continue

                    # skip rpms built from nosrc rpms
                    if 'nosrc' in y.sourcerpm:
                        continue

                    if y.sourcerpm not in srcs:
                        srcs[y.sourcerpm] = set()
                    srcs[y.sourcerpm].add(y.location)

            for src, locs in srcs.iteritems():
                log.warn('missing srpm: %s' % src)
                log.warn('for rpm(s):')
                for loc in sorted(locs):
                    log.warn('\t%s' % loc)

        if self._repoMap:
            for binPkg, archStr in self._repoMap.iteritems():
                # lookup the source for the binary package
                srcPkg = self.binPkgMap[binPkg]

                # get the conary version from the source
                conaryVersion = srcPkg.getConaryVersion()

                if binPkg.arch == 'x86_64':
                    arch = 'x86_64'
                elif binPkg.arch == 'noarch':
                    arch = ''
                elif (binPkg.arch.startswith('i') and
                      binPkg.arch.endswith('86') and
                      len(binPkg.arch) == 4):
                    arch = 'x86'
                else:
                    raise RuntimeError

                trvSpec = (binPkg.name, conaryVersion, arch)
                self.useMap.setdefault(trvSpec, set()).update(archStr)

    def loadFileLists(self, client, basePath):
        """
        Parse file information.
        """

        for pkg in client.getFileLists():
            for binPkg in self.binPkgMap.iterkeys():
                if util.packageCompare(pkg, binPkg) == 0:
                    binPkg.files = pkg.files
                    break

    def _createSrcMap(self):
        """
        Create a source map from the binary map if no sources are available.
        """

        def getSourcePackage(nevra, bins):
            # unpack the nevra
            n, e, v, r, a = nevra

            # create a source package object based on the nevra
            srcPkg = self.PkgClass()
            srcPkg.name = n
            srcPkg.epoch = e
            srcPkg.version = v
            srcPkg.release = r
            srcPkg.arch = a

            # grab the first binary package
            pkg = sorted(bins)[0]

            # Set the location of the fake source package to just be the name
            # of the file. The factory will take care of the rest.
            srcPkg.location = pkg.sourcerpm

            return srcPkg

        def synthesizeSource(srcPkg):
            # add source to structures
            if srcPkg.getNevra() not in self._srcMap:
                log.warn('synthesizing source package %s' % srcPkg)
                self._procSrc(srcPkg)

            # Add location mappings for packages that may have once been
            # synthesized so that parsing old manifest files still works.
            elif srcPkg.location not in self.locationMap:
                pkg = self._srcMap[srcPkg.getNevra()]
                self.locationMap[srcPkg.location] = pkg

        # Return if sources should be available in repos.
        if not self._cfg.synthesizeSources:
            return

        defer = set()
        # Create a fake source rpm object for each key in the rpmMap.
        for nevra, bins in self._rpmMap.iteritems():
            srcPkg = getSourcePackage(nevra, bins)

            # Handle sub packages with different epochs that should be taken
            # care of with the epoch fuzzing that happens in finalize. This
            # should only happen with differently named packages.
            if nevra[0] not in [ x.name for x in bins ]:
                defer.add(nevra)
                continue

            # Synthesize the source
            synthesizeSource(srcPkg)

        broken = set()
        # Make an attempt to sort out the binaries that have different names
        # than the related sources.
        for nevra in defer:
            bins = self._rpmMap[nevra]
            srcPkg = getSourcePackage(nevra, bins)

            name, epoch, version, release, arch = nevra
            # Find sources that match on all cases except epoch.
            sources = [ x for x in self._srcMap.iterkeys()
                if (name, version, release, arch) == (x[0], x[2], x[3], x[4]) ]
            # leave it up to fuzzing
            if sources: continue

            # If we get here this is a set of binary packages that have a
            # different name than the source rpm. This is possible, but should
            # be an extremely rare case.
            log.warn('found binary without matching source name %s'
                     % list(bins)[0].name)

            # If this isn't a case of a missmatched epoch, just go ahead and
            # make up a source. What could go wrong?
            synthesizeSource(srcPkg)
            #broken.add((nevra, tuple(bins)))

        # Raise an exception if this ever happens. We can figure out the right
        # thing to do then, purhaps on a case by case basis.
        if broken:
            raise CanNotFindSourceForBinariesError(count=len(broken))
