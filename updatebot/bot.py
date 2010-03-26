#
# Copyright (c) 2008-2010 rPath, Inc.
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
Module for driving the update process.
"""

import time
import logging
import itertools

from updatebot import build
from updatebot import update
from updatebot import pkgsource
from updatebot import advisories

log = logging.getLogger('updatebot.bot')

class Bot(object):
    """
    Top level object for driving update process.
    """

    def __init__(self, cfg):
        self._cfg = cfg

        self._patchSourcePopulated = False

        self._clients = {}
        self._pkgSource = pkgsource.PackageSource(self._cfg)
        self._updater = update.Updater(self._cfg, self._pkgSource)
        self._builder = build.Builder(self._cfg)

        if not self._cfg.disableAdvisories:
            self._advisor = advisories.Advisor(self._cfg, self._pkgSource,
                                               self._cfg.platformName)

    @staticmethod
    def _flattenSetDict(setDict):
        """
        Convert a dictionary with values of sets to a list.
        @param setDict: dictionary of sets
        @type setDict: [set(), set(), ...]
        @return list of items that were in the sets
        """

        return [ x for x in itertools.chain(*setDict.itervalues()) ]

    def create(self, rebuild=False, recreate=None, toCreate=None):
        """
        Do initial imports.

        @param rebuild - rebuild all sources
        @type rebuild - boolean
        @param recreate - recreate all sources or a specific list of packages
        @type recreate - boolean to recreate all sources or a list of specific
                         package names
        @param toCreate - set of source package objects to create, implies recreate.
        @type toCreate - iterable
        """

        start = time.time()
        log.info('starting import')

        # Populate rpm source object from yum metadata.
        self._pkgSource.load()

        # Build list of packages
        if toCreate:
            toPackage = None
        elif type(recreate) == list:
            toPackage = set(recreate)
        elif self._cfg.packageAll:
            toPackage = set()
            for srcName, srcSet in self._pkgSource.srcNameMap.iteritems():
                if len(srcSet) == 0:
                    continue

                srcList = list(srcSet)
                srcList.sort()
                latestSrc = srcList[-1]

                if latestSrc not in self._pkgSource.srcPkgMap:
                    log.warn('not packaging %s, not found in srcPkgMap' % latestSrc.name)
                    continue

                if latestSrc.name in self._cfg.package:
                    log.warn('ignoring %s due to exclude rule' % latestSrc.name)
                    continue

                for binPkg in self._pkgSource.srcPkgMap[latestSrc]:
                    toPackage.add(binPkg.name)

        else:
            toPackage = set(self._cfg.package)


        # Import sources into repository.
        toBuild, parentPkgMap, fail = self._updater.create(
            toPackage,
            buildAll=rebuild,
            recreate=bool(recreate),
            toCreate=toCreate)

        log.info('failed to create %s packages' % len(fail))
        log.info('found %s packages to build' % len(toBuild))

        trvMap = {}
        failed = ()
        if len(toBuild):
            if not rebuild or (rebuild and toCreate):
                # Build all newly imported packages.
                trvMap, failed = self._builder.buildmany(sorted(toBuild))
                log.info('failed to import %s packages' % len(failed))
                if len(failed):
                    for pkg in failed:
                        log.warn('%s' % (pkg, ))
            else:
                # ReBuild all packages.
                trvMap = self._builder.buildsplitarch(sorted(toBuild))
            log.info('import completed successfully')
            log.info('imported %s source packages' % (len(toBuild), ))
        else:
            log.info('no packages found to build, maybe there is a flavor '
                     'configuration issue')

        log.info('elapsed time %s' % (time.time() - start, ))

        # Add any platform packages to the trove map.
        trvMap.update(parentPkgMap)

        return trvMap, failed

    def update(self, force=None, updatePkgs=None, expectedRemovals=None):
        """
        Update the conary repository from the yum repositories.
        @param force: list of packages to update without exception
        @type force: list(pkgName, pkgName, ...)
        @param updatePkgs: set of source package objects to update
        @type updatePkgs: iterable of source package objects
        @param expectedRemovals: set of packages that are expected to be
                                 removed.
        @type expectedRemovals: set of package names
        """

        if force is not None:
            self._cfg.disableUpdateSanity = True
            assert isinstance(force, list)

        updateTroves = None
        if updatePkgs:
            updateTroves = set(((x.name, None, None), x) for x in updatePkgs)

        start = time.time()
        log.info('starting update')

        # Populate rpm source object from yum metadata.
        self._pkgSource.load()

        # Get troves to update and send advisories.
        toAdvise, toUpdate = self._updater.getUpdates(
            updateTroves=updateTroves,
            expectedRemovals=expectedRemovals)

        # If forcing an update, make sure that all packages are listed in
        # toAdvise and toUpdate as needed.
        if force:
            advise = list()
            updates = list()
            for pkg in toAdvise:
                if pkg[1].name in force:
                    advise.append(pkg)
            for pkg in toUpdate:
                if pkg[1].name in force:
                    updates.append(pkg)
            toAdvise = advise
            toUpdate = updates

        if len(toAdvise) == 0:
            log.info('no updates available')
            return

        if not self._cfg.disableAdvisories:
            # Populate patch source now that we know that there are updates
            # available.
            self._advisor.load()

            # Check to see if advisories exist for all required packages.
            self._advisor.check(toAdvise)

        # Update source
        parentPackages = set()
        for nvf, srcPkg in toUpdate:
            toAdvise.remove((nvf, srcPkg))
            newVersion = self._updater.update(nvf, srcPkg)
            if self._updater.isPlatformTrove(newVersion):
                toAdvise.append(((nvf[0], newVersion, nvf[2]), srcPkg))
            else:
                parentPackages.add((nvf[0], newVersion, nvf[2]))

        log.info('looking up binary versions of all parent platform packages')
        parentPkgMap = self._updater.getBinaryVersions(parentPackages,
            labels=self._cfg.platformSearchPath)

        # Make sure to build everything in the toAdvise list, there may be
        # sources that have been updated, but not built.
        buildTroves = set([ x[0] for x in toAdvise ])

        # If importing specific packages, they might require each other so
        # always use buildmany, but wait to commit.
        if updatePkgs:
            trvMap, failed = self._builder.buildmany(buildTroves,
                                                     lateCommit=True)

        # Switch to splitarch if a build is larger than maxBuildSize. This
        # number is kinda arbitrary. Builds tend to break when architectures
        # are combind if the build is significantly large
        elif len(buildTroves) < self._cfg.maxBuildSize:
            trvMap = self._builder.build(buildTroves)
        else:
            trvMap = self._builder.buildsplitarch(buildTroves)

        if not self._cfg.disableAdvisories:
            # Build group.
            grpTrvs = (self._cfg.topSourceGroup, )
            grpTrvMap = self._builder.build(grpTrvs)

            # Promote group.
            # We expect that everything that was built will be published.
            expected = self._flattenSetDict(trvMap)
            toPublish = self._flattenSetDict(grpTrvMap)
            newTroves = self._updater.publish(toPublish, expected,
                                              self._cfg.targetLabel)

            # Mirror out content
            self._updater.mirror()

            # Send advisories.
            self._advisor.send(toAdvise, newTroves)

        log.info('update completed successfully')
        log.info('updated %s packages and sent %s advisories'
                 % (len(toUpdate), len(toAdvise)))
        log.info('elapsed time %s' % (time.time() - start, ))

        # Add any platform packages to the trove map.
        trvMap.update(parentPkgMap)

        return trvMap

    def mirror(self, fullTroveSync=False):
        """
        Mirror platform contents to production repository.
        """

        return self._updater.mirror(fullTroveSync=fullTroveSync)
