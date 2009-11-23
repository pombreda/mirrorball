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
Module for finding packages to update and updating them.
"""

import os
import logging

from rpmutils import rpmvercmp

from updatebot.lib import util
from updatebot import conaryhelper
from updatebot.errors import GroupNotFound
from updatebot.errors import NoManifestFoundError
from updatebot.errors import OldVersionNotFoundError
from updatebot.errors import UpdateGoesBackwardsError
from updatebot.errors import UpdateRemovesPackageError

log = logging.getLogger('updatebot.update')

class Updater(object):
    """
    Class for finding and updating packages.
    """

    def __init__(self, cfg, pkgSource):
        self._cfg = cfg
        self._pkgSource = pkgSource

        self._conaryhelper = conaryhelper.ConaryHelper(self._cfg)

    def getUpdates(self, updateTroves=None):
        """
        Find all packages that need updates and/or advisories from a top level
        binary group.
        @param updateTroves: set of troves to update
        @type updateTroves: iterable
        @return list of packages to send advisories for and list of packages
                to update
        """

        log.info('searching for packages to update')

        toAdvise = []
        toUpdate = []

        # If update set is not specified get the latest versions of packages to
        # update.
        if not updateTroves:
            updateTroves = self._findUpdatableTroves(self._cfg.topGroup)

        for nvf, srpm in updateTroves:
            # Will raise exception if any errors are found, halting execution.
            if self._sanitizeTrove(nvf, srpm):
                toUpdate.append((nvf, srpm))
                toAdvise.append((nvf, srpm))


            # Update versions for things that are already in the repository.
            # The binary version from the group will not be the latest.
            else:
                # Make sure to send advisories for any packages that didn't get
                # sent out last time.
                version = self._conaryhelper.getLatestSourceVersion(nvf[0])
                toAdvise.append(((nvf[0], version, nvf[2]), srpm))


        log.info('found %s troves to update, and %s troves to send advisories'
                 % (len(toUpdate), len(toAdvise)))
        return toAdvise, toUpdate

    def _fltrPkg(self, pkgname):
        """
        Return True if this is a package that should be filtered out.
        """

        if (pkgname.startswith('info-') or
            pkgname.startswith('group-') or
            pkgname.startswith('factory-') or
            pkgname in self._cfg.excludePackages):
            return True

        return False

    def _findUpdatableTroves(self, group):
        """
        Query a group to find packages that need to be updated.
        @param group: package spec for the top level group to query
        @type group: (name, versionObj, flavorObj)
        @return list of nvf and src package object
        """

        # ((name, version, flavor), srpm)
        troves = []
        for name, version, flavor in \
          self._conaryhelper.getSourceTroves(group).iterkeys():
            name = name.split(':')[0]

            # skip special packages
            if self._fltrPkg(name):
                continue

            latestSrpm = self._getLatestSource(name)
            latestVer = util.srpmToConaryVersion(latestSrpm)
            curVer = str(version.trailingRevision().version)
            if rpmvercmp(latestVer, curVer) != 0:
                log.info('found potential updatable trove: %s'
                         % ((name, version, flavor), ))
                log.debug('cny: %s, rpm: %s' % (curVer, latestVer))
                # Add anything that has changed, version may have gone
                # backwards if epoch changes.
                troves.append(((name, version, flavor), latestSrpm))

        log.info('found %s protentially updatable troves' % len(troves))
        return troves

    def getSourceVersionMap(self):
        """
        Query the repository for a list of the latest source names and versions.
        """

        return dict([ (x.split(':')[0], y) for x, y, z in
            self._conaryhelper.getSourceTroves(self._cfg.topGroup).iterkeys()
            if not self._fltrPkg(x.split(':')[0])
        ])

    def _getLatestSource(self, name):
        """
        Get the latest src package for a given package name.
        @param name: name of the package to retrieve
        @type name: string
        @return src package object
        """

        srpms = list(self._pkgSource.srcNameMap[name])
        srpms.sort(util.packagevercmp)
        return srpms[-1]

    def _sanitizeTrove(self, nvf, srpm):
        """
        Verifies the package update to make sure it looks correct and is a
        case that the bot knows how to handle.

        If an error occurs an exception will be raised, otherwise return a
        boolean value whether to update the source component or not. All
        packages that pass this method need to have advisories sent.

        @param nvf: name, version, and flavor of the source component to be
                    updated
        @type nvf: (name, versionObj, flavorObj)
        @param srpm: src pacakge object
        @type srpm: repomd.packagexml._Package
        @return needsUpdate boolean
        @raises UpdateGoesBackwardsError
        @raises UpdateRemovesPackageError
        """

        needsUpdate = False
        newNames = [ (x.name, x.arch) for x in self._pkgSource.srcPkgMap[srpm] ]
        metadata = None

        try:
            manifest = self._conaryhelper.getManifest(nvf[0])
        except NoManifestFoundError, e:
            # Create packages that do not have manifests.
            # TODO: might want to make this a config option?
            log.info('no manifest found for %s, will create package' % nvf[0])
            return True

        for line in manifest:
            # Some manifests were created with double slashes, need to
            # normalize the path to work around this problem.
            line = os.path.normpath(line)
            if line in self._pkgSource.locationMap:
                binPkg = self._pkgSource.locationMap[line]
                srcPkg = self._pkgSource.binPkgMap[binPkg]
            else:
                if metadata is None:
                    pkgs = self._getMetadataFromConaryRepository(nvf[0])
                    metadata = util.Metadata(pkgs)
                if metadata:
                    binPkg = metadata.locationMap[line]
                    srcPkg = metadata.binPkgMap[binPkg]
                else:
                    raise OldVersionNotFoundError(
                                why="can't find metadata for %s" % line)

            # set needsUpdate if version changes
            if util.packagevercmp(srpm, srcPkg) == 1:
                needsUpdate = True

            # make sure new package is actually newer
            if util.packagevercmp(srpm, srcPkg) == -1:
                raise UpdateGoesBackwardsError(why=(srcPkg, srpm))

            # make sure we aren't trying to remove a package
            if ((binPkg.name, binPkg.arch) not in newNames and
                not self._cfg.disableUpdateSanity):
                # Novell releases updates to only the binary rpms of a package
                # that have chnaged. We have to use binaries from the old srpm.
                # Get the last version of the pkg and add it to the srcPkgMap.
                pkgs = list(self._pkgSource.binNameMap[binPkg.name])

                # get the correct arch
                pkg = [ x for x in self._getLatestOfAvailableArches(pkgs)
                        if x.arch == binPkg.arch ][0]

                # Raise an exception if the versions of the packages aren't
                # equal.
                if (rpmvercmp(pkg.epoch, srpm.epoch) != 0 or
                    rpmvercmp(pkg.version, srpm.version) != 0):
                    raise UpdateRemovesPackageError(why='all rpms in the '
                            'manifest should have the same version, trying '
                            'to add %s' % (pkg, ))

                log.warn('using old version of package %s' % (pkg, ))
                self._pkgSource.srcPkgMap[srpm].add(pkg)

        return needsUpdate

    @staticmethod
    def _getLatestOfAvailableArches(pkgLst):
        """
        Given a list of package objects, find the latest versions of each
        package for each name/arch.
        @param pkgLst: list of packages
        @type pkgLst: [repomd.packagexml._Package, ...]
        """

        pkgLst.sort()

        pkgMap = {}
        for pkg in pkgLst:
            key = pkg.name + pkg.arch
            if key not in pkgMap:
                pkgMap[key] = pkg
                continue

            # check if newer, first wins
            if util.packagevercmp(pkg, pkgMap[key]) in (1, ):
                pkgMap[key] = pkg

        ret = pkgMap.values()
        ret.sort()

        return ret

    def create(self, pkgNames=None, buildAll=False, recreate=False, toCreate=None):
        """
        Import a new package into the repository.
        @param pkgNames: list of packages to import
        @type pkgNames: list
        @param buildAll: return a list of all troves found rather than just the new ones.
        @type buildAll: boolean
        @param recreate: a package manifest even if it already exists.
        @type recreate: boolean
        @return new source [(name, version, flavor), ... ]

        @param toCreate: set of packages to update. If this is set all other
                         options are ignored.
        @type toCreate: set of source package objects.
        """

        assert pkgNames or toCreate

        if pkgNames:
            toCreate = set()
        else:
            # Import very specific versions of packages, make sure to recreate
            # them all.
            pkgNames = []
            recreate = False

        log.info('getting existing packages')
        pkgs = self._getExistingPackageNames()

        # Find all of the source to update.
        for pkg in pkgNames:
            if pkg not in self._pkgSource.binNameMap:
                log.warn('no package named %s found in package source' % pkg)
                continue

            srcPkg = self._getPackagesToImport(pkg)

            if srcPkg.name not in pkgs or recreate:
                toCreate.add(srcPkg)

        # Update all of the unique sources.
        fail = set()
        toBuild = set()
        verCache = self._conaryhelper.getLatestVersions()
        for pkg in sorted(toCreate):
            try:
                # Only import packages that haven't been imported before
                version = verCache.get('%s:source' % pkg.name)
                if not version or recreate:
                    log.info('attempting to import %s' % pkg)
                    version = self.update((pkg.name, None, None), pkg)

                if not verCache.get(pkg.name) or buildAll or recreate:
                    toBuild.add((pkg.name, version, None))
                else:
                    log.info('not building %s' % pkg.name)
            except Exception, e:
                log.error('failed to import %s: %s' % (pkg, e))
                fail.add((pkg, e))

        if buildAll and pkgs:
            toBuild.update(
                [ (x, self._conaryhelper.getLatestSourceVersion(x), None)
                  for x in pkgs if not self._fltrPkg(x) ]
            )

        return toBuild, fail

    def _getExistingPackageNames(self):
        """
        Returns a list of names of all sources included in the top level group.
        """

        # W0612 - Unused variable
        # pylint: disable-msg=W0612

        try:
            return [ n.split(':')[0] for n, v, f in
            self._conaryhelper.getSourceTroves(self._cfg.topGroup).iterkeys() ]
        except GroupNotFound:
            return []

    def _getPackagesToImport(self, name):
        """
        Add any missing packages to the srcPkgMap entry for this package.
        @param name: name of the srpm to look for.
        @type name: string
        @return latest source package for the given name
        """

        latestRpm = self._getLatestBinary(name)
        latestSrpm = self._pkgSource.binPkgMap[latestRpm]

        pkgs = {}
        pkgNames = set()
        for pkg in self._pkgSource.srcPkgMap[latestSrpm]:
            pkgNames.add(pkg.name)
            pkgs[(pkg.name, pkg.arch)] = pkg

        for srpm in self._pkgSource.srcNameMap[latestSrpm.name]:
            if latestSrpm.epoch == srpm.epoch and \
               latestSrpm.version == srpm.version:
                for pkg in self._pkgSource.srcPkgMap[srpm]:
                    # Add special handling for packages that have versions in
                    # the names.
                    # FIXME: This is specific to non rpm based platforms right
                    #        now. It needs to be tested on rpm platforms to
                    #        make nothing breaks.
                    if (self._cfg.repositoryFormat != 'rpm'
                        and pkg.name not in pkgNames
                        and pkg.version in pkg.name):
                        continue
                    if (pkg.name, pkg.arch) not in pkgs:
                        pkgs[(pkg.name, pkg.arch)] = pkg

        self._pkgSource.srcPkgMap[latestSrpm] = set(pkgs.values())

        return latestSrpm

    def _getLatestBinary(self, name):
        """
        Find the latest version of a given binary package.
        @param name: name of the package to look for
        @type name: string
        """

        rpms = list(self._pkgSource.binNameMap[name])
        rpms.sort(util.packagevercmp)
        return rpms[-1]

    def update(self, nvf, srcPkg):
        """
        Update rpm manifest in source trove.
        @param nvf: name, version, flavor tuple of source trove
        @type nvf: tuple(name, versionObj, flavorObj)
        @param srcPkg: package object for source rpm
        @type srcPkg: repomd.packagexml._Package
        @return version of the updated source trove
        """

        manifest = self._getManifestFromPkgSource(srcPkg)
        self._conaryhelper.setManifest(nvf[0], manifest)

        # FIXME: This is apt specific for now. Once repomd has been rewritten
        #        to use something other than rpath-xmllib we should be able to
        #        convert this to xobj.
        if (self._cfg.repositoryFormat == 'apt' or
            self._cfg.writePackageMetadata):
            metadata = self._getMetadataFromPkgSource(srcPkg)
            self._conaryhelper.setMetadata(nvf[0], metadata)

        if self._cfg.repositoryFormat == 'yum' and self._cfg.buildFromSource:
            buildrequires = self._getBuildRequiresFromPkgSource(srcPkg)
            self._conaryhelper.setBuildRequires(nvf[0], buildrequires)

        newVersion = self._conaryhelper.commit(nvf[0],
                                    commitMessage=self._cfg.commitMessage)
        return newVersion

    def _getManifestFromPkgSource(self, srcPkg):
        """
        Get the contents of the a manifest file from the pkgSource object.
        @param srcPkg: source rpm package object
        @type srcPkg: repomd.packagexml._Package
        """

        manifest = []

        if self._cfg.repositoryFormat == 'yum' and self._cfg.buildFromSource:
            manifest.append(srcPkg.location)
        else:
            manifestPkgs = list(self._pkgSource.srcPkgMap[srcPkg])
            for pkg in self._getLatestOfAvailableArches(manifestPkgs):
                if hasattr(pkg, 'location'):
                    manifest.append(pkg.location)
                elif hasattr(pkg, 'files'):
                    manifest.extend(pkg.files)
        return manifest

    def _getMetadataFromPkgSource(self, srcPkg):
        """
        Get the data to go into the xml metadata from a srcPkg.
        @param srcPkg: source package object
        @return list of packages
        """

        return self._pkgSource.srcPkgMap[srcPkg]

    def _getMetadataFromConaryRepository(self, pkgName):
        """
        Get the metadata from the repository and generate required mappings.
        @param pkgName: source package name
        @type pkgName: string
        @return dictionary of infomation that looks like a pkgsource.
        """

        return self._conaryhelper.getMetadata(pkgName)

    def _getBuildRequiresFromPkgSource(self, srcPkg):
        """
        Get the buildrequires for a given srcPkg.
        @param srcPkg: source package object
        @return list of build requires
        """

        reqs = []
        for reqType in srcPkg.format:
            if reqType.getName() == 'rpm:requires':
                names = [ x.name.split('(')[0] for x in reqType.iterChildren()
                          if not (hasattr(x, 'isspace') and x.isspace()) ]

                for name in names:
                    if name in self._pkgSource.binNameMap:
                        latest = self._getLatestBinary(name)
                        if latest not in self._pkgSource.binPkgMap:
                            log.warn('%s not found in binPkgMap' % latest)
                            continue
                        src = self._pkgSource.binPkgMap[latest]
                        srcname = src.name
                    else:
                        log.warn('found virtual requires %s in pkg %s' % (name, srcPkg.name))
                        srcname = 'virtual'
                    reqs.append((name, srcname))

        reqs = list(set(reqs))
        return reqs

    def _getBuildRequiresFromConaryRepository(self, pkgName):
        """
        Get the contents of the build requires file from the repository.
        @param pkgName: name of the package
        @type pkgName: string
        @return list of build requires
        """

        return self._conaryhelper.getBuildRequires(pkgName)

    def publish(self, trvLst, expected, targetLabel, checkPackageList=True):
        """
        Publish a group and its contents to a target label.
        @param trvLst: list of troves to publish
        @type trvLst: [(name, version, flavor), ... ]
        @param expected: list of troves that are expected to be published.
        @type expected: [(name, version, flavor), ...]
        @param targetLabel: table to publish to
        @type targetLabel: conary Label object
        @param checkPackageList: verify list of packages being promoted or not.
        @type checkPackageList: boolean
        """

        return self._conaryhelper.promote(
            trvLst,
            expected,
            self._cfg.sourceLabel,
            targetLabel,
            checkPackageList=checkPackageList,
            extraPromoteTroves=self._cfg.extraPromoteTroves
        )

    def mirror(self, fullTroveSync=False):
        """
        If a mirror is configured, mirror out any changes.
        """

        return self._conaryhelper.mirror(fullTroveSync=fullTroveSync)

    def setTroveMetadata(self, srcTrvSpec, binTrvSet):
        """
        Add metadata from a pkgsource to the specified troves.
        @param srcTrvSpec: source to use to find srcPkg
        @type srcTrvSpec: (name:source, conary.versions.Version, None)
        @param binTrvSet: set of binaries built from the given source.
        @type binTrvSet: set((n, v, f), ...)
        """

        srcName = srcTrvSpec[0].split(':')[0]
        srcPkg = self._getLatestSource(srcName)

        trvSpecs = list(binTrvSet)

        # FIXME: figure out why conary does't let you set metadata on
        #        source troves.
        #trvSpecs.append(srcTrvSpec)

        self._conaryhelper.setTroveMetadata(trvSpecs,
            license=srcPkg.license,
            desc=srcPkg.description,
            shortDesc=srcPkg.summary,
        )
