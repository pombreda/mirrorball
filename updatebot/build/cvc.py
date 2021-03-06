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
An abstraction layer around cvc cook.
"""

import os
import copy
import time
import logging
import tempfile

log = logging.getLogger('updatebot.build.cvc')

from conary import versions
from conary import conarycfg
from conary.deps import deps
from conary.build import cook
from conary import conaryclient

from updatebot.lib import conarycallbacks
from updatebot.errors import LocalCookFailedError

class Cvc(object):
    """
    This is initially intended to only implement interfaces for cooking groups
    locally, but could and should be extended to building other kinds of
    troves. This would be useful for building packages that do not depend on
    environment, such as factories and superclasses. Additionally implementing
    a general abstraction around cvc for all cvc operations could be very handy.
    @param cfg: updatebot config object
    @type cfg: updatebot.config.UpdateBotConfiguration
    @param ccfg: conary configuration object
    @type ccfg: conary.conarycfg.ConaryConfiguration
    @param client: conary client object
    @type client: conary.conaryclient.ConaryClient
    @param inputFormatter: method to format trove lists into approriate tuples.
    @type inputFormatter: method
    """

    def __init__(self, cfg, ccfg, inputFormatter, dispatcher):
        self._cfg = cfg
        # Since there's no clone method on a cfg object, use the pickle protocol
        self._ccfg = ccfg.__class__()
        self._ccfg.__setstate__(ccfg.__getstate__())
        self._dispatcher = dispatcher
        self._formatInput = inputFormatter

        # Restet dbPath to the default value for local cooking.
        self._ccfg.resetToDefault('dbPath')

        self._client = conaryclient.ConaryClient(self._ccfg)

    def cook(self, troveSpecs, flavorFilter=None, commit=True, callback=None):
        """
        Cook a set of trove specs, currently limited to groups.
        @params troveSpecs: list of name, version, and flavor tuples.
        @type troveSpecs: [(name, version, flavor), ... ]
        @param flavorFilter: Allow caller to filter out the contexts that they
                             want to build. This is mostly used for group
                             building where a given group should not be built
                             for a context.
        @type flavorFilter: iterable of context names.
        @param commit: Optional parameter to control when a changeset is
                       committed.
        @type commit: boolean
        @param callback: Cook callback to use when building.
        @type callback: conary.build.cook.CookCallback
        """

        # TODO: Look at conary.build.cook.cookCommand for how to setup
        #       environment when building anything other than groups.

        troveSpecs = self._formatInput(troveSpecs)

        if commit:
            changeSetFile = None
        else:
            fd, changeSetFile = tempfile.mkstemp(prefix='changeset-')
            os.close(fd)

        if flavorFilter:
            troveSpecs = self._filterTroveSpecs(troveSpecs, flavorFilter)

        # make sure all troves are groups
        assert not [ x for x in troveSpecs if not x[0].startswith('group-') ]

        # make sure that all groups are the same name and version.
        assert len(set([ (x[0], x[1]) for x in troveSpecs])) == 1

        # pulled from conary.cvc
        groupCookOptions = cook.GroupCookOptions(
            alwaysBumpCount = True,
            errorOnFlavorChange = False,
            shortenFlavors = self._ccfg.shortenGroupFlavors
        )

        # extract flavor set
        flavors = set([ x[2] for x in troveSpecs ])
        item = (troveSpecs[0][0], troveSpecs[0][1], flavors)

        if not callback:
            callback = conarycallbacks.UpdateBotCookCallback()

        built = cook.cookItem(
            self._client.repos,
            self._ccfg,
            item,
            ignoreDeps=True,
            logBuild=True,
            callback=callback,
            groupOptions=groupCookOptions,
            changeSetFile=changeSetFile,
        )

        if built is None:
            raise LocalCookFailedError(troveSpecs=troveSpecs)

        components, csFile = built

        if not components:
            raise LocalCookFailedError(troveSpecs=troveSpecs)

        if csFile is None:
            log.info('changeset committed to repository')

        # Convert version strings to version objects to match the output from
        # rMake builds.
        results = set((x, versions.VersionFromString(y), z)
                      for x, y, z in components)

        res = { (troveSpecs[0][0], troveSpecs[0][1], None): results }

        if commit:
            return res
        else:
            return changeSetFile, res

    def commitChangeSetFile(self, changeSetFile, callback=None):
        """
        Expose commit changeset interface.
        @param changeSetFile: changeset file name
        @type changeSetFile: str
        @param callback: optional commit callback.
        @type callback: conary.callbacks.ChangesetCallback
        """

        log.info('starting commit of %s' % changeSetFile)

        start = time.time()
        res = self._client.repos.commitChangeSetFile(
            changeSetFile, callback=callback)

        elapsed = time.time() - start
        log.info('completed commit of %s in %s' % (changeSetFile, elapsed))

        return True

    def build(self, trvSpec, flavorFilter=None):
        """
        Build trove locally.
        @param trvSpec: trove spec to build.
        @type trvSpec: tuple(str, conary.versions.VersionFromString,
                                  conary.deps.deps.Flavor)
        @param flavorFilter: Allow caller to filter out the contexts that they
                             want to build. This is mostly used for group
                             building where a given group should not be built
                             for a context.
        @type flavorFilter: iterable of context names.
        @return status results instance.
        """

        return self._dispatcher.build(trvSpec, flavorFilter=flavorFilter)

    def _filterTroveSpecs(self, troveSpecs, useFlags):
        """
        Filter trove specs based on a list of use flags. This is only applicable
        to groups.
        @param troveSpecs: iterable of nvf tuples.
        @type troveSpecs: list(tuple(str, conary.versions.VersionFromString,
                                     conary.deps.deps.Flavor), ...)
        @param useFlags: iterable of valid use flags (x86 and x86_64)
        @type useFlags: list(str, ...)
        @return modified list of trove specs
        @rtype list(tuple(str, conary.versions.VersionFromString,
                          conary.deps.deps.Flavor), ...)
        """

        useMap = {
            'x86': deps.parseFlavor('is: x86'),
            'x86_64': deps.parseFlavor('is: x86_64'),
        }

        specs = set()
        for n, v, f in troveSpecs:
            for flag in useFlags:
                if f.satisfies(useMap[flag]):
                    specs.add((n, v, f))

        return list(specs)
